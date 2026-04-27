"""Session + event storage backed by SQLite (WAL) with an in-memory live tail.

The data plane has two layers that the API layer composes against:

* A *durable* SQLite database (WAL-journaled). Sessions and events are
  persisted; rehydration on startup recovers prior sessions and marks any
  that were mid-capture as ``interrupted``.
* An *in-memory* per-session ring buffer (``deque(maxlen=event_ring_size)``)
  used as the live tail for the WebSocket stream and the cheap
  ``store.events()`` lookup. Inserts to SQLite happen asynchronously on a
  background writer thread so the capture callback never blocks on disk.

The public surface (``store``/``hub`` singletons, ``ActivityEvent``,
``ProcessSelectRequest``, ``SessionResponse``, ``EventHub``, and the
``SessionStore`` methods used by the router) is unchanged from the
previous in-memory implementation, plus three additions for the new
filter / export / status-persistence routes:

* :meth:`SessionStore.query_events` — filtered, paginated reads from SQL.
* :meth:`SessionStore.iter_events` — streaming reads for export.
* :meth:`SessionStore.mark_session_status` — durable status updates.

Connection-handling pattern
---------------------------
SQLite connections are not safe to share across threads by default. The
writer thread owns its **own** connection (it is the only thread that
calls ``INSERT`` / ``UPDATE`` against the data tables). All reader paths
(query_events / iter_events / rehydrate / mark_session_status) share a
single ``check_same_thread=False`` connection guarded by ``self._lock``.
This keeps reader code simple — no per-call connect/teardown — while the
write path is hot enough to justify a dedicated connection that owns the
write lock.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import queue
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from service.capture_service import CaptureService

from .config import get_settings
from .db.migrations import apply_migrations

logger = logging.getLogger("activity_tracker.store")

# Repo root: backend/app/store.py -> parents[2]
BASE_DIR = Path(__file__).resolve().parents[2]

# Writer-thread tunables. Kept module-private; ``Settings`` is intentionally
# unchanged so other agents touching config don't conflict with this one.
_WRITER_BATCH_MAX = 1000
_WRITER_BATCH_INTERVAL = 0.1  # seconds


def resolve_db_path() -> Path:
    """Resolve the configured ``db_path``, treating relative paths as repo-root relative."""
    p = Path(get_settings().db_path)
    return p if p.is_absolute() else BASE_DIR / p


# ---- DTOs ------------------------------------------------------------------


class ProcessSelectRequest(BaseModel):
    exe_path: str | None = Field(default=None)
    pid: int | None = Field(default=None)


class SessionResponse(BaseModel):
    session_id: str
    exe_path: str
    pid: int
    created_at: str
    status: str
    capture: str
    capture_error: str | None = None


@dataclass
class ActivityEvent:
    id: str
    session_id: str
    timestamp: str
    kind: str
    pid: int | None = None
    ppid: int | None = None
    path: str | None = None
    target: str | None = None
    operation: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


# ---- session/event store ---------------------------------------------------


class SessionStore:
    """Sessions + events with SQLite durability and an in-memory live tail."""

    # Sentinel object pushed onto the writer queue to request thread shutdown.
    _SHUTDOWN = object()

    def __init__(self) -> None:
        settings = get_settings()
        self._ring_size: int = settings.event_ring_size

        self._sessions: dict[str, dict[str, Any]] = {}
        self._events: dict[str, deque[ActivityEvent]] = defaultdict(
            lambda: deque(maxlen=self._ring_size)
        )
        self._capture: dict[str, CaptureService] = {}

        # ``check_same_thread=False`` lets the FastAPI request thread and any
        # background helper share this connection; ``self._lock`` makes that
        # safe. The writer thread does NOT use this connection — see
        # ``_writer_loop``.
        db_path = resolve_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        apply_migrations(self._conn)

        # Writer thread + queue for batched INSERTs.
        self._write_q: queue.Queue[Any] = queue.Queue()
        self._writer_stop = threading.Event()
        # ``_drained`` is set whenever the writer has fully drained the queue
        # AND committed; ``flush()`` waits on it. Cleared at every enqueue.
        self._drained = threading.Event()
        self._drained.set()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="activity-tracker-store-writer",
            daemon=True,
        )
        self._writer_thread.start()

        # Replay persisted sessions; any session that was mid-capture when the
        # process died gets marked interrupted so the UI doesn't claim it's
        # still tracking.
        self._rehydrate()

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "exe_path": row["exe_path"],
            "pid": row["pid"],
            "created_at": row["created_at"],
            "status": row["status"],
            "capture": row["capture"],
            "capture_error": row["capture_error"],
        }

    @staticmethod
    def _row_to_event_dict(row: sqlite3.Row) -> dict[str, Any]:
        details_raw = row["details_json"]
        try:
            details = json.loads(details_raw) if details_raw else {}
        except json.JSONDecodeError:
            details = {"_raw": details_raw}
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            # Expose the legacy key the UI already consumes; ``ts`` is the
            # storage column, ``timestamp`` is the wire/dataclass field.
            "timestamp": row["ts"],
            "ts": row["ts"],
            "kind": row["kind"],
            "pid": row["pid"],
            "ppid": row["ppid"],
            "path": row["path"],
            "target": row["target"],
            "operation": row["operation"],
            "details": details,
        }

    def _rehydrate(self) -> None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT session_id, exe_path, pid, pid_create_time, created_at,"
                "       status, capture, capture_error FROM sessions"
            )
            rows = cur.fetchall()

            interrupted: list[str] = []
            for row in rows:
                session = self._row_to_session(row)
                if session["capture"] in ("live", "tracking", "initializing"):
                    session["capture"] = "interrupted"
                    session["status"] = "interrupted"
                    interrupted.append(session["session_id"])
                self._sessions[session["session_id"]] = session

            if interrupted:
                self._conn.executemany(
                    "UPDATE sessions SET status=?, capture=? WHERE session_id=?",
                    [("interrupted", "interrupted", sid) for sid in interrupted],
                )
                self._conn.commit()
                logger.info("rehydrate: marked %d session(s) interrupted", len(interrupted))

    # ---- writer thread ----------------------------------------------------

    def _writer_loop(self) -> None:
        """Drain the write queue in batches and INSERT in a single tx."""
        # Dedicated connection — owned exclusively by this thread.
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        # Schedule the next retention sweep.
        settings = get_settings()
        retention_interval = max(1, int(settings.db_retention_check_minutes)) * 60
        next_retention = time.monotonic() + retention_interval
        try:
            apply_migrations(conn)  # cheap; ensures pragmas on this conn too
            while True:
                batch: list[ActivityEvent] = []
                shutdown_requested = False

                # Periodic retention sweep — bounds DB size at sustained
                # capture rates so events.db doesn't grow forever.
                if time.monotonic() >= next_retention:
                    try:
                        self._run_retention(conn)
                    except Exception:  # noqa: BLE001
                        logger.exception("writer: retention sweep failed")
                    next_retention = time.monotonic() + retention_interval

                # Block until at least one item or the stop event fires.
                try:
                    first = self._write_q.get(timeout=0.5)
                except queue.Empty:
                    if self._writer_stop.is_set() and self._write_q.empty():
                        return
                    # Nothing pending; mark drained so flush() can wake.
                    self._drained.set()
                    continue

                if first is self._SHUTDOWN:
                    shutdown_requested = True
                else:
                    batch.append(first)

                # Pull additional items up to the batch size or interval.
                deadline = time.monotonic() + _WRITER_BATCH_INTERVAL
                while len(batch) < _WRITER_BATCH_MAX:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        item = self._write_q.get(timeout=remaining)
                    except queue.Empty:
                        break
                    if item is self._SHUTDOWN:
                        shutdown_requested = True
                        break
                    batch.append(item)

                if batch:
                    try:
                        self._flush_batch(conn, batch)
                    except Exception:  # noqa: BLE001
                        logger.exception("writer: batch insert failed (size=%d)", len(batch))

                if self._write_q.empty():
                    self._drained.set()

                if shutdown_requested:
                    # Drain anything that arrived after the sentinel.
                    leftovers: list[ActivityEvent] = []
                    while True:
                        try:
                            item = self._write_q.get_nowait()
                        except queue.Empty:
                            break
                        if item is self._SHUTDOWN:
                            continue
                        leftovers.append(item)
                    if leftovers:
                        try:
                            self._flush_batch(conn, leftovers)
                        except Exception:  # noqa: BLE001
                            logger.exception("writer: shutdown flush failed")
                    self._drained.set()
                    return
        finally:
            with contextlib.suppress(Exception):
                conn.close()

    @staticmethod
    def _run_retention(conn: sqlite3.Connection) -> None:
        """Drop events older than ``db_retention_days``. No-op when set to 0.

        Runs inside the writer thread so it shares the writer's transaction
        pattern. Called periodically from ``_writer_loop``.
        """
        days = int(get_settings().db_retention_days)
        if days <= 0:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        deleted = cur.rowcount or 0
        conn.commit()
        if deleted:
            logger.info("retention: pruned %d events older than %d day(s)", deleted, days)

    @staticmethod
    def _flush_batch(conn: sqlite3.Connection, batch: list[ActivityEvent]) -> None:
        rows = [
            (
                ev.id,
                ev.session_id,
                ev.timestamp,
                ev.kind,
                ev.pid,
                ev.ppid,
                ev.path,
                ev.target,
                ev.operation,
                json.dumps(ev.details, default=str) if ev.details else None,
            )
            for ev in batch
        ]
        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO events"
                " (id, session_id, ts, kind, pid, ppid, path, target, operation, details_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )

    # ---- public API: sessions --------------------------------------------

    def create(
        self,
        exe_path: str,
        pid: int,
        capture_status: str,
        capture_error: str | None,
    ) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "exe_path": exe_path,
            "pid": pid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "tracking" if capture_status == "live" else capture_status,
            "capture": capture_status,
            "capture_error": capture_error,
        }
        with self._lock:
            self._sessions[session_id] = session
            self._conn.execute(
                "INSERT INTO sessions"
                " (session_id, exe_path, pid, pid_create_time, created_at, status, capture, capture_error)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    exe_path,
                    pid,
                    None,
                    session["created_at"],
                    session["status"],
                    session["capture"],
                    capture_error,
                ),
            )
            self._conn.commit()
        return session

    def attach_capture(self, session_id: str, service: CaptureService) -> None:
        self._capture[session_id] = service

    def detach_capture(self, session_id: str) -> CaptureService | None:
        return self._capture.pop(session_id, None)

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict[str, Any]]:
        return list(self._sessions.values())

    def mark_session_status(
        self,
        session_id: str,
        *,
        status: str,
        capture: str,
        capture_error: str | None = None,
    ) -> None:
        """Update both the in-memory session dict and the persisted row."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session["status"] = status
                session["capture"] = capture
                session["capture_error"] = capture_error
            self._conn.execute(
                "UPDATE sessions SET status=?, capture=?, capture_error=? WHERE session_id=?",
                (status, capture, capture_error, session_id),
            )
            self._conn.commit()

    # ---- public API: events ----------------------------------------------

    def add_event(self, event: ActivityEvent) -> None:
        # Ring buffer for the live tail.
        self._events[event.session_id].append(event)
        # Hand off to the writer thread; non-blocking.
        self._drained.clear()
        self._write_q.put(event)

    def events(self, session_id: str) -> list[ActivityEvent]:
        """Live-tail view from the in-memory ring buffer (no SQL)."""
        return list(self._events[session_id])

    def flush(self, timeout: float = 5.0) -> None:
        """Block until all queued writes have been committed.

        Used by tests and by ``shutdown()``. Safe to call from any thread.
        """
        # If the queue is empty AND the writer hasn't been woken since, we're
        # already drained.
        deadline = time.monotonic() + timeout
        while True:
            if self._write_q.empty() and self._drained.is_set():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("flush: timed out with %d pending writes", self._write_q.qsize())
                return
            self._drained.wait(timeout=min(0.1, remaining))

    def query_events(
        self,
        session_id: str,
        *,
        kind: str | None = None,
        pid: int | None = None,
        since: str | None = None,
        until: str | None = None,
        q: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Filtered, paginated SQL read. Returns rows as dicts (details parsed)."""
        sql, params = self._build_query(
            session_id, kind=kind, pid=pid, since=since, until=until, q=q
        )
        sql += " ORDER BY ts ASC, id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_event_dict(r) for r in rows]

    def iter_events(
        self,
        session_id: str,
        *,
        kind: str | None = None,
        pid: int | None = None,
        since: str | None = None,
        until: str | None = None,
        q: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream ``ts ASC`` rows for export.

        We use a private connection per call so the iterator can outlive a
        single request without holding the shared lock for the entire body.
        """
        sql, params = self._build_query(
            session_id, kind=kind, pid=pid, since=since, until=until, q=q
        )
        sql += " ORDER BY ts ASC, id ASC"
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(sql, params)
            for row in cur:
                yield self._row_to_event_dict(row)
        finally:
            conn.close()

    @staticmethod
    def _build_query(
        session_id: str,
        *,
        kind: str | None,
        pid: int | None,
        since: str | None,
        until: str | None,
        q: str | None,
    ) -> tuple[str, list[Any]]:
        clauses = ["session_id = ?"]
        params: list[Any] = [session_id]
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if pid is not None:
            clauses.append("pid = ?")
            params.append(pid)
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("ts <= ?")
            params.append(until)
        if q:
            like = f"%{q}%"
            clauses.append(
                "(COALESCE(path,'') LIKE ?"
                " OR COALESCE(target,'') LIKE ?"
                " OR COALESCE(operation,'') LIKE ?"
                " OR COALESCE(details_json,'') LIKE ?)"
            )
            params.extend([like, like, like, like])
        sql = (
            "SELECT id, session_id, ts, kind, pid, ppid, path, target, operation, details_json"
            " FROM events WHERE " + " AND ".join(clauses)
        )
        return sql, params

    # ---- public API: capture services ------------------------------------

    def all_capture_services(self) -> list[CaptureService]:
        return list(self._capture.values())

    def shutdown(self) -> None:
        """Stop the writer thread, flush pending events, then halt capture."""
        # Signal writer; flush after.
        self._writer_stop.set()
        try:
            self._write_q.put_nowait(self._SHUTDOWN)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._writer_thread.join(timeout=5.0)
        except Exception:  # noqa: BLE001
            logger.warning("writer thread join failed", exc_info=True)

        for service in self.all_capture_services():
            try:
                service.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("capture stop on shutdown failed: %s", exc)

        with contextlib.suppress(Exception):
            self._conn.close()


# ---- pub/sub (unchanged) ---------------------------------------------------


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._sub_q_size: int = get_settings().subscriber_queue_size
        # Count of subscribers disconnected because their queue overflowed.
        # Surfaced via /api/health and /metrics so silent drops are visible.
        self.dropped_subscribers: int = 0

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue_: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._sub_q_size)
        self._subscribers[session_id].add(queue_)
        return queue_

    def unsubscribe(self, session_id: str, queue_: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[session_id].discard(queue_)

    async def publish(self, session_id: str, payload: dict[str, Any]) -> None:
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for queue_ in self._subscribers[session_id]:
            try:
                queue_.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(queue_)
        if dead:
            self.dropped_subscribers += len(dead)
            logger.warning(
                "EventHub: dropped %d slow subscriber(s) on session %s "
                "(total=%d). Increase TRACKER_SUBSCRIBER_QUEUE_SIZE if this recurs.",
                len(dead), session_id, self.dropped_subscribers,
            )
        for queue_ in dead:
            self._subscribers[session_id].discard(queue_)


# Module-level singletons. The API router and shutdown hook bind to these.
store = SessionStore()
hub = EventHub()

"""HTTP + WebSocket routes for the Activity Tracker control plane.

Everything user-visible lives here: session CRUD, process listing, the event
ingest endpoint, the per-session WebSocket stream, and the SPA index route.
The router is mounted by ``backend.app.main``.

Helpers ``_resolve_target`` (pid/exe -> concrete pid) and ``_make_event_callback``
(thread-safe bridge from the capture thread back into the asyncio loop) live
here because they are tightly coupled to the request/response cycle.
"""

from __future__ import annotations

import asyncio
import csv as _csv
import io as _io
import json
import json as _json
import logging
import subprocess
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse

from service.capture_service import (
    CaptureService,
    CaptureTarget,
    _native_binary_path,
    is_admin,
)

from .store import (
    ActivityEvent,
    ProcessSelectRequest,
    SessionResponse,
    hub,
    store,
)

logger = logging.getLogger("activity_tracker.api")

# Repo root: backend/app/api_routes.py -> parents[2]
BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "ui" / "dist"

router = APIRouter()


# ---- helpers ---------------------------------------------------------------

def _resolve_target(req: ProcessSelectRequest) -> tuple[int, str]:
    """Turn a request (pid or exe_path) into (pid, resolved_exe_path)."""
    if req.pid is not None:
        try:
            proc = psutil.Process(req.pid)
            exe = proc.exe() or req.exe_path or proc.name()
            return req.pid, exe
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            raise HTTPException(status_code=404, detail=f"pid {req.pid}: {exc}") from exc

    if not req.exe_path:
        raise HTTPException(status_code=400, detail="provide either pid or exe_path")

    target_path = Path(req.exe_path)
    target_name = target_path.name.lower()
    matches: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = (proc.info.get("exe") or "").lower()
            name = (proc.info.get("name") or "").lower()
            if exe and Path(exe) == target_path:
                matches.append(proc)
            elif name == target_name:
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"no running process matches {req.exe_path}",
        )
    proc = matches[0]
    return proc.pid, proc.info.get("exe") or req.exe_path


def _make_event_callback(loop: asyncio.AbstractEventLoop, session_id: str):
    """Build the sync callback that capture_service hands events to (on its thread)."""
    def callback(payload: dict[str, Any]) -> None:
        event = ActivityEvent(
            id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            kind=payload.get("kind", "unknown"),
            pid=payload.get("pid"),
            ppid=payload.get("ppid"),
            path=payload.get("path"),
            target=payload.get("target"),
            operation=payload.get("operation"),
            details=payload.get("details") or {},
        )
        store.add_event(event)
        try:
            asyncio.run_coroutine_threadsafe(
                hub.publish(session_id, asdict(event)), loop
            )
        except RuntimeError:
            pass

    return callback


# ---- routes ----------------------------------------------------------------

def _list_processes_native() -> list[dict[str, Any]] | None:
    """Try the native ``tracker_capture --list-processes`` binary.

    Returns the parsed NDJSON rows on success, or ``None`` on any failure
    (binary missing, non-zero exit, timeout, OS error). The HTTP handler
    falls back to ``psutil.process_iter`` whenever this returns ``None``,
    so the backend keeps working even when the native build is absent.
    """
    binary = _native_binary_path()
    if binary is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - argv is fully controlled.
            [str(binary), "--list-processes"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("native --list-processes failed: %s", exc)
        return None
    if result.returncode != 0:
        logger.warning(
            "native --list-processes exited %s: %s",
            result.returncode,
            result.stderr[:200],
        )
        return None
    items: list[dict[str, Any]] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except (ValueError, json.JSONDecodeError):
            continue
    return items


@router.get("/api/processes")
def list_processes() -> dict[str, Any]:
    items = _list_processes_native()
    if items is None:
        # Fallback: native binary missing or failed -- enumerate via psutil.
        items = []
        for proc in psutil.process_iter(
            ["pid", "name", "exe", "username", "ppid"]
        ):
            try:
                info = proc.info
                items.append(
                    {
                        "pid": info.get("pid"),
                        "ppid": info.get("ppid"),
                        "name": info.get("name"),
                        "exe": info.get("exe"),
                        "username": info.get("username"),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    items.sort(key=lambda x: (x.get("name") or "").lower())
    return {"items": items, "admin": is_admin()}


@router.get("/api/processes/icon")
def process_icon(exe: str = Query(..., min_length=1)) -> Response:
    """Return the Windows icon for an EXE as a PNG.

    The path is validated against ``is_safe_exe_path`` (rejects relative,
    UNC, and traversal-laden inputs). On any failure -- non-existent file,
    non-Windows host, GDI failure -- we serve a 1x1 transparent PNG so the
    UI never has to handle a 4xx/5xx for a missing icon.
    """
    from backend.app.icons import TRANSPARENT_PNG, get_or_extract_icon
    from backend.app.observability import is_safe_exe_path

    if not is_safe_exe_path(exe):
        raise HTTPException(status_code=400, detail="invalid exe path")
    try:
        png = get_or_extract_icon(exe)
    except Exception:  # noqa: BLE001 - never bubble 5xx for a UI icon
        png = None
    if not png:
        png = TRANSPARENT_PNG
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/api/sessions", response_model=SessionResponse)
async def create_session(request: ProcessSelectRequest) -> SessionResponse:
    pid, exe_path = _resolve_target(request)

    if not is_admin():
        session = store.create(
            exe_path=exe_path,
            pid=pid,
            capture_status="needs_admin",
            capture_error="Backend is not Administrator; ETW capture disabled.",
        )
        return SessionResponse(**session)

    # Reserve the session id first so the capture callback can publish to it
    # from the very first event.
    session = store.create(
        exe_path=exe_path,
        pid=pid,
        capture_status="initializing",
        capture_error=None,
    )
    session_id = session["session_id"]

    loop = asyncio.get_running_loop()
    service = CaptureService(
        target=CaptureTarget(exe_path=exe_path, pid=pid),
        on_event=_make_event_callback(loop, session_id),
    )
    try:
        service.start()
    except PermissionError as exc:
        session["capture"] = "needs_admin"
        session["status"] = "needs_admin"
        session["capture_error"] = str(exc)
        store.mark_session_status(
            session_id,
            status="needs_admin",
            capture="needs_admin",
            capture_error=str(exc),
        )
        return SessionResponse(**session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to start capture")
        session["capture"] = "failed"
        session["status"] = "failed"
        session["capture_error"] = f"{type(exc).__name__}: {exc}"
        store.mark_session_status(
            session_id,
            status="failed",
            capture="failed",
            capture_error=f"{type(exc).__name__}: {exc}",
        )
        return SessionResponse(**session)

    store.attach_capture(session_id, service)
    session["capture"] = "live"
    session["status"] = "tracking"
    store.mark_session_status(
        session_id, status="tracking", capture="live", capture_error=None
    )
    return SessionResponse(**session)


@router.delete("/api/sessions/{session_id}")
def stop_session(
    session_id: str,
    purge: bool = Query(False, description="If true, also delete the session row + its events from the DB."),
) -> dict[str, str]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    service = store.detach_capture(session_id)
    if service is not None:
        service.stop()
    if purge:
        store.purge_session(session_id)
        return {"status": "purged"}
    session = store.get(session_id)
    if session is not None:
        session["status"] = "stopped"
        session["capture"] = "stopped"
        store.mark_session_status(
            session_id, status="stopped", capture="stopped", capture_error=None
        )
    return {"status": "stopped"}


@router.post("/api/sessions/cleanup")
def cleanup_sessions() -> dict[str, Any]:
    """Bulk-delete every session whose capture is not currently active.

    Useful for trimming the SessionList after a long debugging run that
    leaves a tail of stopped / interrupted / needs_admin sessions for the
    same exe. Active live sessions are preserved.
    """
    removed = store.purge_inactive_sessions()
    return {"status": "purged", "count": len(removed), "ids": removed}


@router.get("/api/sessions")
def list_sessions() -> dict[str, list[dict[str, Any]]]:
    return {"items": store.list()}


@router.get("/api/sessions/{session_id}/events")
def get_events(
    session_id: str,
    kind: str | None = Query(None),
    pid: int | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    q: str | None = Query(None),
    # Repeat the param to allow-list operations: ?operation=write&operation=create
    operation: list[str] | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> dict[str, list[dict[str, Any]]]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "items": store.query_events(
            session_id, kind=kind, pid=pid, since=since, until=until, q=q,
            operations=operation, limit=limit, offset=offset,
        )
    }


@router.get("/api/sessions/{session_id}/export")
def export_events(
    session_id: str,
    format: str = Query("jsonl", pattern="^(csv|jsonl)$"),
    kind: str | None = None,
    since: str | None = None,
    until: str | None = None,
    q: str | None = None,
    operation: list[str] | None = Query(None),
):
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    if format == "jsonl":
        def gen():
            for row in store.iter_events(
                session_id, kind=kind, since=since, until=until, q=q, operations=operation
            ):
                yield (_json.dumps(row, default=str) + "\n").encode()
        media = "application/x-jsonlines"
    else:
        cols = [
            "id", "session_id", "ts", "kind", "pid", "ppid",
            "path", "target", "operation", "details",
        ]

        def gen():
            buf = _io.StringIO()
            w = _csv.writer(buf)
            w.writerow(cols)
            yield buf.getvalue().encode()
            buf.seek(0)
            buf.truncate()
            for row in store.iter_events(
                session_id, kind=kind, since=since, until=until, q=q, operations=operation
            ):
                details = row.get("details")
                w.writerow([
                    row.get(c) if c != "details" else _json.dumps(details, default=str)
                    for c in cols
                ])
                yield buf.getvalue().encode()
                buf.seek(0)
                buf.truncate()
        media = "text/csv"

    fname = f"tracker-{session_id}.{format}"
    return StreamingResponse(
        gen(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/api/sessions/{session_id}/emit")
async def emit_event(session_id: str, payload: dict[str, Any]) -> dict[str, str]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    event = ActivityEvent(
        id=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        kind=payload.get("kind", "custom"),
        pid=payload.get("pid"),
        ppid=payload.get("ppid"),
        path=payload.get("path"),
        target=payload.get("target"),
        operation=payload.get("operation"),
        details=payload.get("details", {}),
    )
    store.add_event(event)
    await hub.publish(session_id, asdict(event))
    return {"status": "accepted"}


@router.websocket("/ws/sessions/{session_id}")
async def stream_session(
    websocket: WebSocket,
    session_id: str,
    since: str | None = Query(None),
    replay: bool = Query(True),
) -> None:
    """WebSocket event stream.

    Query params:
      - ``since``: ISO timestamp. Only events with ``timestamp > since`` are
        included in the replay phase. Use this on reconnect so the client
        doesn't receive events it already has via HTTP backfill.
      - ``replay``: when False, skip the ring-buffer replay entirely and
        only stream new events. Useful when the client has already loaded
        history via ``GET /api/sessions/{id}/events``.
    """
    if store.get(session_id) is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue = hub.subscribe(session_id)
    try:
        # Replay buffered history filtered by `since` (if provided). Skip
        # entirely when ``replay=false``. ``default=str`` keeps non-JSON-native
        # fields (datetimes, bytes converted upstream) from killing the
        # connection.
        if replay:
            for event in store.events(session_id):
                if since is not None and (event.timestamp or "") <= since:
                    continue
                try:
                    await websocket.send_text(json.dumps(asdict(event), default=str))
                except (WebSocketDisconnect, ConnectionError, RuntimeError):
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ws replay send failed: %s", exc)
                    continue
        # Tail new events.
        while True:
            payload = await queue.get()
            try:
                await websocket.send_text(json.dumps(payload, default=str))
            except (WebSocketDisconnect, ConnectionError, RuntimeError):
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("ws tail send failed: %s", exc)
                continue
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(session_id, queue)


@router.get("/api/logs/streams")
def logs_streams() -> dict[str, Any]:
    """List available log streams with their on-disk size + path."""
    from backend.app.observability import list_log_streams

    log_dir = BASE_DIR / "logs"
    try:
        from backend.app.config import get_settings

        settings = get_settings()
        candidate = Path(settings.log_dir)
        log_dir = candidate if candidate.is_absolute() else BASE_DIR / candidate
    except Exception:  # noqa: BLE001
        pass
    return {"streams": list_log_streams(), "log_dir": str(log_dir)}


@router.get("/api/logs/{stream}")
def logs_tail(
    stream: str,
    tail: int = Query(200, ge=1, le=5000),
) -> dict[str, Any]:
    """Return the last ``tail`` lines of ``stream`` as parsed JSON entries."""
    from backend.app.observability import read_log_tail

    items = read_log_tail(stream, tail)
    return {"items": items, "stream": stream, "tail": tail}


@router.websocket("/ws/logs/{stream}")
async def logs_stream_ws(
    websocket: WebSocket,
    stream: str,
    backlog: int = Query(100, ge=0, le=2000),
) -> None:
    """Live tail a log file. Sends ``backlog`` recent lines then polls for new
    bytes. Pass ``backlog=0`` on reconnect to skip the replay and avoid
    duplicating lines the client already has.
    """
    from backend.app.config import get_settings
    from backend.app.observability import LOG_STREAM_FILENAMES, read_log_tail

    if stream not in LOG_STREAM_FILENAMES:
        await websocket.close(code=4404)
        return
    await websocket.accept()

    settings = get_settings()
    log_dir = Path(settings.log_dir)
    if not log_dir.is_absolute():
        log_dir = BASE_DIR / log_dir
    p = log_dir / LOG_STREAM_FILENAMES[stream]

    # Send up to ``backlog`` lines (skip when 0).
    if backlog > 0:
        backlog_items = read_log_tail(stream, backlog)
        for item in backlog_items:
            await websocket.send_text(_json.dumps(item))

    last_size = p.stat().st_size if p.exists() else 0
    try:
        while True:
            await asyncio.sleep(0.25)
            if not p.exists():
                continue
            try:
                current = p.stat().st_size
            except OSError:
                continue
            if current < last_size:
                # File rotated; reset to start.
                last_size = 0
            if current == last_size:
                continue
            try:
                with p.open("rb") as f:
                    f.seek(last_size)
                    chunk = f.read(current - last_size).decode(
                        "utf-8", errors="replace"
                    )
            except OSError:
                continue
            last_size = current
            for line in chunk.splitlines():
                if not line.strip():
                    continue
                try:
                    payload: dict[str, Any] = _json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    payload = {"message": line, "raw": True}
                await websocket.send_text(_json.dumps(payload))
    except WebSocketDisconnect:
        pass


@router.get("/favicon.ico")
def favicon() -> FileResponse:
    """Serve the UI favicon — separate route so /assets mount isn't needed."""
    fav = STATIC_DIR / "favicon.ico"
    if not fav.exists():
        raise HTTPException(status_code=404, detail="favicon not built")
    return FileResponse(fav, media_type="image/x-icon")


@router.get("/")
def index() -> FileResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="ui not built")
    return FileResponse(index_file)

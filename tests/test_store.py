"""Tests for the SQLite-backed SessionStore.

The fixture forces ``TRACKER_DB_PATH`` to a tmp path, then reloads the
``backend.app.store`` module so the module-level ``store`` singleton picks up
the new path. Each test gets a freshly-constructed store with an isolated db.
"""

from __future__ import annotations

import importlib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def fresh_store(monkeypatch, tmp_path):
    """Force a fresh SQLite-backed SessionStore at a tmp path."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("TRACKER_DB_PATH", str(db_file))
    from backend.app import config

    config.get_settings.cache_clear()
    # Reload store module so its module-level singleton picks up the new path.
    from backend.app import store as store_mod

    importlib.reload(store_mod)
    yield store_mod.store
    store_mod.store.shutdown()


def _ts(offset_ms: int = 0) -> str:
    base = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(milliseconds=offset_ms)).isoformat()


def _make_event(session_id: str, *, ts: str, kind: str = "process",
                pid: int | None = 1234, path: str | None = None,
                target: str | None = None, operation: str | None = None,
                details: dict | None = None):
    from backend.app.store import ActivityEvent

    return ActivityEvent(
        id=uuid.uuid4().hex,
        session_id=session_id,
        timestamp=ts,
        kind=kind,
        pid=pid,
        ppid=None,
        path=path,
        target=target,
        operation=operation,
        details=details or {},
    )


def test_create_persists(fresh_store, tmp_path):
    session = fresh_store.create("C:/x.exe", 1234, "tracking", None)
    assert "session_id" in session
    assert session["exe_path"] == "C:/x.exe"
    assert session["pid"] == 1234

    # Verify durably written via a fresh sqlite connection.
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    try:
        rows = conn.execute(
            "SELECT session_id, exe_path, pid FROM sessions WHERE session_id=?",
            (session["session_id"],),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "C:/x.exe"
    assert rows[0][2] == 1234


def test_rehydrate_marks_interrupted(monkeypatch, tmp_path):
    """A session that was 'tracking' when the process died should be rehydrated as 'interrupted'."""
    db_file = tmp_path / "rehydrate.db"
    monkeypatch.setenv("TRACKER_DB_PATH", str(db_file))
    from backend.app import config

    config.get_settings.cache_clear()
    from backend.app import store as store_mod

    importlib.reload(store_mod)
    s = store_mod.store.create("C:/x.exe", 9, "live", None)
    sid = s["session_id"]
    # Status should reflect a "tracking-ish" state for the rehydrate path.
    assert store_mod.store.get(sid)["capture"] == "live"
    store_mod.store.shutdown()

    # Simulate process restart by reloading the store module on the same db path.
    config.get_settings.cache_clear()
    importlib.reload(store_mod)
    try:
        rehydrated = store_mod.store.get(sid)
        assert rehydrated is not None
        assert rehydrated["capture"] == "interrupted"
        assert rehydrated["status"] == "interrupted"
    finally:
        store_mod.store.shutdown()


def test_event_insert_and_query(fresh_store):
    s = fresh_store.create("C:/x.exe", 1, "tracking", None)
    sid = s["session_id"]
    events = [
        _make_event(sid, ts=_ts(0), kind="process", pid=1234, path="A"),
        _make_event(sid, ts=_ts(1), kind="file", pid=1234, path="B"),
        _make_event(sid, ts=_ts(2), kind="file", pid=9999, path="C"),
        _make_event(sid, ts=_ts(3), kind="registry", pid=1234, path="D"),
        _make_event(sid, ts=_ts(4), kind="network", pid=1234, path="E"),
    ]
    for ev in events:
        fresh_store.add_event(ev)
    fresh_store.flush()

    rows = fresh_store.query_events(sid)
    assert len(rows) == 5
    timestamps = [r["ts"] for r in rows]
    assert timestamps == sorted(timestamps)

    file_rows = fresh_store.query_events(sid, kind="file")
    assert len(file_rows) == 2
    assert all(r["kind"] == "file" for r in file_rows)

    pid_rows = fresh_store.query_events(sid, pid=1234)
    assert len(pid_rows) == 4
    assert all(r["pid"] == 1234 for r in pid_rows)


def test_query_q_substring(fresh_store):
    s = fresh_store.create("C:/x.exe", 1, "tracking", None)
    sid = s["session_id"]
    fresh_store.add_event(_make_event(sid, ts=_ts(0), kind="file",
                                       path="C:/Users/x/AppData/Local/foo"))
    fresh_store.add_event(_make_event(sid, ts=_ts(1), kind="file",
                                       path="C:/Windows/System32/bar.dll"))
    fresh_store.add_event(_make_event(sid, ts=_ts(2), kind="file",
                                       target="zzz/AppData/things"))
    fresh_store.add_event(_make_event(sid, ts=_ts(3), kind="file",
                                       operation="open"))
    fresh_store.add_event(_make_event(sid, ts=_ts(4), kind="file",
                                       details={"note": "AppData reference"}))
    fresh_store.flush()

    rows = fresh_store.query_events(sid, q="AppData")
    assert len(rows) == 3
    for r in rows:
        haystack = " ".join(
            str(r.get(k) or "") for k in ("path", "target", "operation")
        ) + " " + str(r.get("details") or "")
        assert "AppData" in haystack


def test_iter_events_streams(fresh_store):
    s = fresh_store.create("C:/x.exe", 1, "tracking", None)
    sid = s["session_id"]
    for i in range(1000):
        fresh_store.add_event(_make_event(sid, ts=_ts(i), kind="file", pid=1))
    fresh_store.flush()

    rows = list(fresh_store.iter_events(sid))
    assert len(rows) == 1000
    timestamps = [r["ts"] for r in rows]
    assert timestamps == sorted(timestamps)


def test_query_pagination(fresh_store):
    s = fresh_store.create("C:/x.exe", 1, "tracking", None)
    sid = s["session_id"]
    for i in range(50):
        fresh_store.add_event(_make_event(sid, ts=_ts(i), kind="file", pid=1))
    fresh_store.flush()

    page = fresh_store.query_events(sid, limit=10, offset=20)
    assert len(page) == 10
    expected = [_ts(i) for i in range(20, 30)]
    assert [r["ts"] for r in page] == expected


def test_mark_session_status_persists(fresh_store, tmp_path):
    s = fresh_store.create("C:/x.exe", 1, "tracking", None)
    sid = s["session_id"]
    fresh_store.mark_session_status(
        sid, status="stopped", capture="stopped", capture_error=None
    )

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    try:
        row = conn.execute(
            "SELECT status, capture, capture_error FROM sessions WHERE session_id=?",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "stopped"
    assert row[1] == "stopped"
    assert row[2] is None

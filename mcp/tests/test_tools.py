"""Unit tests for individual tool functions, exercised against respx mocks."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from mcp_tracker import tools


pytestmark = pytest.mark.asyncio


SAMPLE_HEALTH = {
    "status": "ok",
    "admin": False,
    "uptime_seconds": 12.0,
    "sessions_live": 1,
    "sessions_total": 2,
    "events_buffered": 5,
    "subscribers": 0,
    "captures": [
        {"session_id": "s1", "target_pid": 1234, "events_emitted": 5},
    ],
    "log_dir": "C:/logs",
}

SAMPLE_PROCESSES = {
    "items": [
        {"pid": 100, "ppid": 1, "name": "notepad.exe", "exe": "C:/Windows/notepad.exe", "username": "u"},
        {"pid": 200, "ppid": 1, "name": "chrome.exe", "exe": "C:/Program Files/chrome.exe", "username": "u"},
    ],
    "admin": False,
}

SAMPLE_SESSIONS = {
    "items": [
        {
            "session_id": "s1",
            "exe_path": "C:/x.exe",
            "pid": 1234,
            "created_at": "2026-04-28T00:00:00Z",
            "status": "live",
            "capture": "running",
            "capture_error": None,
        }
    ]
}


async def test_get_health(mock_tracker, client):
    mock_tracker.get("/api/health").mock(return_value=httpx.Response(200, json=SAMPLE_HEALTH))
    out = await tools.get_health(client)
    assert out["status"] == "ok"
    assert out["sessions_live"] == 1


async def test_list_processes_filter(mock_tracker, client):
    mock_tracker.get("/api/processes").mock(return_value=httpx.Response(200, json=SAMPLE_PROCESSES))
    out = await tools.list_processes(client, name_contains="chrome")
    assert len(out["items"]) == 1
    assert out["items"][0]["name"] == "chrome.exe"


async def test_list_processes_no_filter(mock_tracker, client):
    mock_tracker.get("/api/processes").mock(return_value=httpx.Response(200, json=SAMPLE_PROCESSES))
    out = await tools.list_processes(client)
    assert len(out["items"]) == 2


async def test_list_and_get_session(mock_tracker, client):
    mock_tracker.get("/api/sessions").mock(return_value=httpx.Response(200, json=SAMPLE_SESSIONS))
    sessions = await tools.list_sessions(client)
    assert sessions["items"][0]["session_id"] == "s1"

    mock_tracker.get("/api/sessions").mock(return_value=httpx.Response(200, json=SAMPLE_SESSIONS))
    one = await tools.get_session(client, "s1")
    assert one["pid"] == 1234


async def test_get_session_not_found(mock_tracker, client):
    from mcp_tracker.errors import TrackerError

    mock_tracker.get("/api/sessions").mock(return_value=httpx.Response(200, json={"items": []}))
    with pytest.raises(TrackerError):
        await tools.get_session(client, "nope")


async def test_start_session_requires_arg(client):
    from mcp_tracker.errors import TrackerError

    with pytest.raises(TrackerError):
        await tools.start_session(client)


async def test_start_session_pid(mock_tracker, client):
    expected = {**SAMPLE_SESSIONS["items"][0]}
    mock_tracker.post("/api/sessions").mock(
        return_value=httpx.Response(200, json=expected)
    )
    out = await tools.start_session(client, pid=1234)
    assert out["session_id"] == "s1"


async def test_stop_session(mock_tracker, client):
    mock_tracker.delete("/api/sessions/s1").mock(
        return_value=httpx.Response(200, json={"status": "stopped"})
    )
    out = await tools.stop_session(client, "s1")
    assert out["status"] == "stopped"


async def test_query_events_pagination(mock_tracker, client):
    # First call returns exactly `limit` items → next_cursor expected.
    items_full = [
        {"id": str(i), "session_id": "s1", "kind": "file", "ts": f"2026-01-01T00:00:0{i}Z"}
        for i in range(5)
    ]
    route = mock_tracker.get("/api/sessions/s1/events").mock(
        return_value=httpx.Response(200, json={"items": items_full})
    )
    out = await tools.query_events(client, session_id="s1", limit=5)
    assert len(out["items"]) == 5
    assert "next_cursor" in out
    # The encoded cursor should point at offset=5
    import base64

    decoded = json.loads(base64.urlsafe_b64decode(out["next_cursor"].encode()).decode())
    assert decoded == {"offset": 5}

    # Second call short — no next_cursor.
    route.mock(return_value=httpx.Response(200, json={"items": items_full[:2]}))
    out2 = await tools.query_events(
        client, session_id="s1", limit=5, cursor=out["next_cursor"]
    )
    assert "next_cursor" not in out2
    # Verify offset was forwarded as a query param.
    last_request = route.calls.last.request
    assert "offset=5" in str(last_request.url)


async def test_search_events(mock_tracker, client):
    mock_tracker.get("/api/sessions/s1/events").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    out = await tools.search_events(client, session_id="s1", q="AppData")
    assert out["total_returned"] == 0


async def test_tail_events_returns_immediately(mock_tracker, client):
    mock_tracker.get("/api/sessions/s1/events").mock(
        return_value=httpx.Response(200, json={"items": [
            {"id": "1", "session_id": "s1", "kind": "file", "ts": "2026-01-01T00:00:00Z"}
        ] * 50})
    )
    out = await tools.tail_events(client, session_id="s1", max_wait_seconds=0, limit=10)
    assert len(out["items"]) >= 10


async def test_get_capture_stats_all(mock_tracker, client):
    mock_tracker.get("/api/health").mock(return_value=httpx.Response(200, json=SAMPLE_HEALTH))
    out = await tools.get_capture_stats(client)
    assert out["captures"][0]["session_id"] == "s1"


async def test_get_capture_stats_by_session(mock_tracker, client):
    mock_tracker.get("/api/health").mock(return_value=httpx.Response(200, json=SAMPLE_HEALTH))
    out = await tools.get_capture_stats(client, session_id="s1")
    assert out["target_pid"] == 1234


async def test_emit_gated(mock_tracker, client, monkeypatch):
    from mcp_tracker.errors import TrackerError
    from mcp_tracker.config import get_settings

    monkeypatch.delenv("MCP_TRACKER_ALLOW_EMIT", raising=False)
    get_settings.cache_clear()
    with pytest.raises(TrackerError):
        await tools.emit_event(client, session_id="s1", note="hi")


async def test_emit_allowed(mock_tracker, client, monkeypatch):
    from mcp_tracker.config import get_settings

    monkeypatch.setenv("MCP_TRACKER_ALLOW_EMIT", "1")
    get_settings.cache_clear()
    mock_tracker.post("/api/sessions/s1/emit").mock(
        return_value=httpx.Response(200, json={"status": "accepted"})
    )
    out = await tools.emit_event(client, session_id="s1", note="hello", details={"x": 1})
    assert out["status"] == "accepted"


async def test_summarize_session(mock_tracker, client):
    items = [
        {"id": "1", "session_id": "s1", "kind": "file", "pid": 100, "path": "/a", "ts": "2026-01-01T00:00:01Z"},
        {"id": "2", "session_id": "s1", "kind": "file", "pid": 100, "path": "/a", "ts": "2026-01-01T00:00:02Z"},
        {"id": "3", "session_id": "s1", "kind": "registry", "pid": 200, "target": "HKLM/Run", "ts": "2026-01-01T00:00:03Z"},
    ]
    # First call returns all items; second returns empty (loop exits).
    mock_tracker.get("/api/sessions/s1/events").mock(
        side_effect=[
            httpx.Response(200, json={"items": items}),
            httpx.Response(200, json={"items": []}),
        ]
    )
    out = await tools.summarize_session(client, session_id="s1")
    assert out["events_considered"] == 3
    assert out["counts_by_kind"]["file"] == 2
    assert out["counts_by_kind"]["registry"] == 1
    assert sorted(out["unique_pids"]) == [100, 200]
    assert out["time_bounds"]["earliest"] == "2026-01-01T00:00:01Z"
    assert out["time_bounds"]["latest"] == "2026-01-01T00:00:03Z"


async def test_get_metrics_disabled(mock_tracker, client):
    mock_tracker.get("/metrics").mock(return_value=httpx.Response(501))
    out = await tools.get_metrics(client)
    assert out == {"disabled": True, "reason": "prometheus_client not installed"}


async def test_get_metrics_text(mock_tracker, client):
    mock_tracker.get("/metrics").mock(
        return_value=httpx.Response(
            200,
            text="# HELP foo\nfoo 1\n",
            headers={"content-type": "text/plain; version=0.0.4"},
        )
    )
    out = await tools.get_metrics(client)
    assert "foo 1" in out["text"]
    assert "text/plain" in out["content_type"]


async def test_export_writes_file(mock_tracker, client, downloads_dir):
    csv_body = b"id,kind,ts\n1,file,2026-01-01T00:00:00Z\n2,file,2026-01-01T00:00:01Z\n"
    mock_tracker.get("/api/sessions/s1/export").mock(
        return_value=httpx.Response(200, content=csv_body, headers={"content-type": "text/csv"})
    )
    out = await tools.export_session(client, session_id="s1", format="csv")
    assert out["format"] == "csv"
    assert out["bytes"] == len(csv_body)
    # 3 newlines total → 2 events after subtracting the header
    assert out["event_count"] == 2
    from pathlib import Path

    assert Path(out["path"]).exists()
    assert Path(out["path"]).parent == downloads_dir


async def test_export_invalid_format(client):
    from mcp_tracker.errors import TrackerError

    with pytest.raises(TrackerError):
        await tools.export_session(client, session_id="s1", format="xml")


async def test_cursor_helpers_roundtrip():
    from mcp_tracker.tools import _decode_cursor, _encode_cursor

    c = _encode_cursor(42)
    assert _decode_cursor(c) == 42
    assert _decode_cursor(None) == 0


async def test_invalid_cursor_raises():
    from mcp_tracker.errors import TrackerError
    from mcp_tracker.tools import _decode_cursor

    with pytest.raises(TrackerError):
        _decode_cursor("@@@not-base64@@@")

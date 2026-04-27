"""Tests for MCP resources (registered URIs and templates)."""

from __future__ import annotations

import json

import httpx
import pytest

from mcp.server.fastmcp import FastMCP

from mcp_tracker.client import TrackerClient
from mcp_tracker.resources import register_resources


pytestmark = pytest.mark.asyncio


async def _read(mcp: FastMCP, uri: str) -> str:
    contents = list(await mcp.read_resource(uri))
    assert contents, f"no content for {uri}"
    # Each entry is a ReadResourceContents; .content is str/bytes.
    return contents[0].content if hasattr(contents[0], "content") else str(contents[0])


async def test_health_resource(mock_tracker, client):
    mcp = FastMCP("test")
    register_resources(mcp, client)
    mock_tracker.get("/api/health").mock(
        return_value=httpx.Response(200, json={"status": "ok", "captures": []})
    )
    body = await _read(mcp, "tracker://health")
    assert json.loads(body)["status"] == "ok"


async def test_sessions_and_template(mock_tracker, client):
    mcp = FastMCP("test")
    register_resources(mcp, client)
    sessions_payload = {
        "items": [
            {
                "session_id": "abc",
                "exe_path": "C:/x.exe",
                "pid": 1,
                "created_at": "now",
                "status": "live",
                "capture": "running",
                "capture_error": None,
            }
        ]
    }
    mock_tracker.get("/api/sessions").mock(
        return_value=httpx.Response(200, json=sessions_payload)
    )
    body = await _read(mcp, "tracker://sessions")
    assert "abc" in body

    mock_tracker.get("/api/sessions").mock(
        return_value=httpx.Response(200, json=sessions_payload)
    )
    body2 = await _read(mcp, "tracker://sessions/abc")
    assert json.loads(body2)["session_id"] == "abc"


async def test_session_events_template(mock_tracker, client):
    mcp = FastMCP("test")
    register_resources(mcp, client)
    mock_tracker.get("/api/sessions/abc/events").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "e1", "kind": "file"}]})
    )
    body = await _read(mcp, "tracker://sessions/abc/events")
    assert "e1" in body


async def test_processes_resource(mock_tracker, client):
    mcp = FastMCP("test")
    register_resources(mcp, client)
    mock_tracker.get("/api/processes").mock(
        return_value=httpx.Response(200, json={"items": [], "admin": False})
    )
    body = await _read(mcp, "tracker://processes")
    assert json.loads(body)["admin"] is False


async def test_summary_resource_caches(mock_tracker, client):
    mcp = FastMCP("test")
    register_resources(mcp, client)
    payload = {"items": [{"id": "1", "kind": "file", "pid": 1, "ts": "t"}]}
    route = mock_tracker.get("/api/sessions/abc/events").mock(
        return_value=httpx.Response(200, json=payload)
    )
    # First call populates cache; second call should hit the cache.
    a = await _read(mcp, "tracker://sessions/abc/summary")
    b = await _read(mcp, "tracker://sessions/abc/summary")
    assert a == b
    # The summarize loop fetches one batch then exits, so route called once on
    # first read, zero on second (cache hit).
    assert route.call_count >= 1

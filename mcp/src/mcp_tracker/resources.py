"""MCP resources exposing read-only views of tracker state."""

from __future__ import annotations

import json
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import _cache
from .client import TrackerClient
from .errors import TrackerError
from .tools import summarize_session


_SUMMARY_TTL_SECONDS = 5.0


def _dump(obj: Any) -> str:
    return json.dumps(obj, default=str, indent=2)


def register_resources(mcp: FastMCP, client: TrackerClient) -> None:
    """Bind every tracker:// resource onto the FastMCP server."""

    @mcp.resource(
        "tracker://health",
        name="tracker_health",
        mime_type="application/json",
        description="Live tracker /api/health snapshot.",
    )
    async def health_resource() -> str:
        return _dump(await client.health())

    @mcp.resource(
        "tracker://sessions",
        name="tracker_sessions",
        mime_type="application/json",
        description="Every tracker session (live and stopped).",
    )
    async def sessions_resource() -> str:
        return _dump(await client.sessions())

    @mcp.resource(
        "tracker://sessions/{session_id}",
        name="tracker_session",
        mime_type="application/json",
        description="A single tracker session by id.",
    )
    async def session_resource(session_id: str) -> str:
        items = (await client.sessions()).get("items", [])
        for s in items:
            if s.get("session_id") == session_id:
                return _dump(s)
        raise TrackerError(f"Session not found: {session_id}")

    @mcp.resource(
        "tracker://sessions/{session_id}/events",
        name="tracker_session_events",
        mime_type="application/json",
        description="Latest 200 events for a session (no filtering).",
    )
    async def session_events_resource(session_id: str) -> str:
        return _dump(await client.events(session_id, limit=200))

    @mcp.resource(
        "tracker://sessions/{session_id}/summary",
        name="tracker_session_summary",
        mime_type="application/json",
        description="Aggregated kind/path/pid rollup of a session, cached for 5 seconds.",
    )
    async def session_summary_resource(session_id: str) -> str:
        key = ("summary", session_id)
        now = time.monotonic()
        cached = _cache.get(key)
        if cached and now - cached[0] < _SUMMARY_TTL_SECONDS:
            return cached[1]
        summary = await summarize_session(client, session_id=session_id)
        text = _dump(summary)
        _cache[key] = (now, text)
        return text

    @mcp.resource(
        "tracker://processes",
        name="tracker_processes",
        mime_type="application/json",
        description="Currently running OS processes from /api/processes.",
    )
    async def processes_resource() -> str:
        return _dump(await client.processes())

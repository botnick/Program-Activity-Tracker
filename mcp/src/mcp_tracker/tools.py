"""MCP tool implementations.

Each tool is a plain async function taking a ``TrackerClient`` so it can be
unit-tested without spinning up a FastMCP instance. ``register_tools`` binds
thin wrappers onto a FastMCP server and tags them with the public tool name +
description.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections import Counter
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import TrackerClient
from .config import get_settings
from .errors import TrackerError


# --- cursor helpers --------------------------------------------------------


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"offset": offset}).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())["offset"])
    except Exception as exc:  # noqa: BLE001
        raise TrackerError(f"Invalid cursor: {exc}") from exc


# --- plain async functions (test-friendly) ---------------------------------


async def get_health(client: TrackerClient) -> dict:
    return await client.health()


async def list_processes(client: TrackerClient, name_contains: str | None = None) -> dict:
    data = await client.processes()
    if name_contains:
        needle = name_contains.lower()
        items = data.get("items", [])
        data = dict(data)
        data["items"] = [
            p
            for p in items
            if needle in (p.get("name") or "").lower()
            or needle in (p.get("exe") or "").lower()
        ]
    return data


async def list_sessions(client: TrackerClient) -> dict:
    return await client.sessions()


async def get_session(client: TrackerClient, session_id: str) -> dict:
    items = (await client.sessions()).get("items", [])
    for s in items:
        if s.get("session_id") == session_id:
            return s
    raise TrackerError(f"Session not found: {session_id}")


async def start_session(
    client: TrackerClient,
    pid: int | None = None,
    exe_path: str | None = None,
) -> dict:
    if pid is None and not exe_path:
        raise TrackerError("Provide either pid or exe_path.")
    return await client.create_session(pid=pid, exe_path=exe_path)


async def stop_session(client: TrackerClient, session_id: str) -> dict:
    return await client.stop_session(session_id)


async def query_events(
    client: TrackerClient,
    session_id: str,
    kind: str | None = None,
    pid: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> dict:
    offset = _decode_cursor(cursor)
    limit = min(max(int(limit), 1), 1000)
    data = await client.events(
        session_id,
        kind=kind,
        pid=pid,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    items = data.get("items", [])
    result: dict[str, Any] = {"items": items, "total_returned": len(items)}
    if len(items) == limit:
        result["next_cursor"] = _encode_cursor(offset + limit)
    return result


async def search_events(
    client: TrackerClient,
    session_id: str,
    q: str,
    kind: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    offset = _decode_cursor(cursor)
    limit = min(max(int(limit), 1), 1000)
    data = await client.events(
        session_id,
        kind=kind,
        q=q,
        limit=limit,
        offset=offset,
    )
    items = data.get("items", [])
    result: dict[str, Any] = {"items": items, "total_returned": len(items)}
    if len(items) == limit:
        result["next_cursor"] = _encode_cursor(offset + limit)
    return result


async def tail_events(
    client: TrackerClient,
    session_id: str,
    since: str | None = None,
    max_wait_seconds: int = 5,
    limit: int = 100,
) -> dict:
    end = asyncio.get_event_loop().time() + max(0, int(max_wait_seconds))
    latest = since
    items: list[dict] = []
    # Always do at least one fetch even if max_wait_seconds == 0.
    while True:
        data = await client.events(session_id, since=latest, limit=limit)
        new_items = data.get("items", [])
        if new_items:
            items.extend(new_items)
            latest = (
                new_items[-1].get("ts")
                or new_items[-1].get("timestamp")
                or latest
            )
            if len(items) >= limit:
                break
        if asyncio.get_event_loop().time() >= end:
            break
        await asyncio.sleep(0.5)
    return {"items": items, "latest_timestamp": latest}


async def export_session(
    client: TrackerClient,
    session_id: str,
    format: str,
    kind: str | None = None,
    since: str | None = None,
    until: str | None = None,
    q: str | None = None,
) -> dict:
    from .exporting import stream_to_file

    if format not in ("csv", "jsonl"):
        raise TrackerError("format must be 'csv' or 'jsonl'")
    path, byte_count, line_count = await stream_to_file(
        client,
        session_id,
        format,
        kind=kind,
        since=since,
        until=until,
        q=q,
    )
    return {
        "path": str(path),
        "bytes": byte_count,
        "event_count": line_count,
        "format": format,
    }


async def get_capture_stats(
    client: TrackerClient,
    session_id: str | None = None,
) -> dict:
    h = await client.health()
    captures = h.get("captures", []) or []
    if session_id is None:
        return {"captures": captures}
    for c in captures:
        if c.get("session_id") == session_id:
            return c
        if str(c.get("target_pid")) == session_id:
            return c
        sn = c.get("session_name") or ""
        if isinstance(sn, str) and sn.endswith(f"-{session_id}"):
            return c
    raise TrackerError(f"No live capture for session {session_id}")


async def emit_event(
    client: TrackerClient,
    session_id: str,
    note: str,
    kind: str = "annotation",
    details: dict | None = None,
) -> dict:
    if not get_settings().allow_emit:
        raise TrackerError(
            "emit_event is disabled. Set MCP_TRACKER_ALLOW_EMIT=1 to enable."
        )
    return await client.emit(
        session_id,
        {"kind": kind, "operation": note, "details": details or {}},
    )


async def summarize_session(
    client: TrackerClient,
    session_id: str,
    max_events: int = 5000,
) -> dict:
    max_events = min(max(int(max_events), 1), 50000)
    items: list[dict] = []
    offset = 0
    per_call = 1000
    while len(items) < max_events:
        remaining = max_events - len(items)
        batch_limit = min(per_call, remaining)
        data = await client.events(session_id, limit=batch_limit, offset=offset)
        chunk = data.get("items", [])
        if not chunk:
            break
        items.extend(chunk)
        offset += len(chunk)
        if len(chunk) < batch_limit:
            break

    counts_by_kind: Counter = Counter(e.get("kind") for e in items if e.get("kind"))
    path_counter: Counter = Counter()
    pid_set: set[int] = set()
    timestamps: list[str] = []
    for e in items:
        p = e.get("path") or e.get("target")
        if p:
            path_counter[p] += 1
        pid = e.get("pid")
        if pid is not None:
            try:
                pid_set.add(int(pid))
            except (TypeError, ValueError):
                pass
        ts = e.get("ts") or e.get("timestamp")
        if ts:
            timestamps.append(ts)

    return {
        "session_id": session_id,
        "events_considered": len(items),
        "counts_by_kind": dict(counts_by_kind),
        "top_paths": path_counter.most_common(10),
        "unique_pids": sorted(pid_set),
        "time_bounds": {
            "earliest": min(timestamps) if timestamps else None,
            "latest": max(timestamps) if timestamps else None,
        },
    }


async def get_metrics(client: TrackerClient) -> dict:
    return await client.metrics()


# --- registration ----------------------------------------------------------


def register_tools(mcp: FastMCP, client: TrackerClient) -> None:
    """Bind every tool above to ``mcp`` with its public name + description."""

    @mcp.tool(name="get_health")
    async def _get_health() -> dict:
        """Return tracker health: admin status, uptime, live session count, per-capture stats, log dir."""
        return await get_health(client)

    @mcp.tool(name="list_processes")
    async def _list_processes(name_contains: str | None = None) -> dict:
        """List currently running OS processes (pid/ppid/name/exe/username). Filter by substring of name or exe path."""
        return await list_processes(client, name_contains=name_contains)

    @mcp.tool(name="list_sessions")
    async def _list_sessions() -> dict:
        """List every tracker session (live and stopped) with status and capture state."""
        return await list_sessions(client)

    @mcp.tool(name="get_session")
    async def _get_session(session_id: str) -> dict:
        """Get a single session by id, including capture status and any error."""
        return await get_session(client, session_id)

    @mcp.tool(name="start_session")
    async def _start_session(
        pid: int | None = None, exe_path: str | None = None
    ) -> dict:
        """Start tracking a process by pid OR exe_path. Requires admin for real ETW capture."""
        return await start_session(client, pid=pid, exe_path=exe_path)

    @mcp.tool(name="stop_session")
    async def _stop_session(session_id: str) -> dict:
        """Stop a running session and release ETW resources. Events remain queryable."""
        return await stop_session(client, session_id)

    @mcp.tool(name="query_events")
    async def _query_events(
        session_id: str,
        kind: str | None = None,
        pid: int | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict:
        """Page through stored events for a session with structured filters and a base64 offset cursor."""
        return await query_events(
            client,
            session_id=session_id,
            kind=kind,
            pid=pid,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )

    @mcp.tool(name="search_events")
    async def _search_events(
        session_id: str,
        q: str,
        kind: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict:
        """Substring search events across path/target/operation/details for a session."""
        return await search_events(
            client,
            session_id=session_id,
            q=q,
            kind=kind,
            limit=limit,
            cursor=cursor,
        )

    @mcp.tool(name="tail_events")
    async def _tail_events(
        session_id: str,
        since: str | None = None,
        max_wait_seconds: int = 5,
        limit: int = 100,
    ) -> dict:
        """Wait briefly for new events on a session. Poll-based; use repeatedly to follow a live session."""
        return await tail_events(
            client,
            session_id=session_id,
            since=since,
            max_wait_seconds=max_wait_seconds,
            limit=limit,
        )

    @mcp.tool(name="export_session")
    async def _export_session(
        session_id: str,
        format: str,
        kind: str | None = None,
        since: str | None = None,
        until: str | None = None,
        q: str | None = None,
    ) -> dict:
        """Export a session's events to a CSV or JSONL file in Downloads. Returns the absolute file path."""
        return await export_session(
            client,
            session_id=session_id,
            format=format,
            kind=kind,
            since=since,
            until=until,
            q=q,
        )

    @mcp.tool(name="get_capture_stats")
    async def _get_capture_stats(session_id: str | None = None) -> dict:
        """Return per-session ETW capture statistics from /api/health."""
        return await get_capture_stats(client, session_id=session_id)

    @mcp.tool(name="emit_event")
    async def _emit_event(
        session_id: str,
        note: str,
        kind: str = "annotation",
        details: dict | None = None,
    ) -> dict:
        """Inject a custom annotation event into a session. Gated by MCP_TRACKER_ALLOW_EMIT=1."""
        return await emit_event(
            client,
            session_id=session_id,
            note=note,
            kind=kind,
            details=details,
        )

    @mcp.tool(name="summarize_session")
    async def _summarize_session(session_id: str, max_events: int = 5000) -> dict:
        """Compute a quick rollup of a session: counts by kind, top 10 paths, unique pids, time bounds."""
        return await summarize_session(
            client, session_id=session_id, max_events=max_events
        )

    @mcp.tool(name="get_metrics")
    async def _get_metrics() -> dict:
        """Fetch raw Prometheus metrics text from the tracker, or note disabled if /metrics returns 501."""
        return await get_metrics(client)

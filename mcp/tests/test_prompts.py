"""Tests for MCP prompts: registration + rendered text contents."""

from __future__ import annotations

import pytest

from mcp.server.fastmcp import FastMCP

from mcp_tracker.prompts import register_prompts


pytestmark = pytest.mark.asyncio


async def test_prompt_count():
    mcp = FastMCP("test")
    register_prompts(mcp)
    prompts = await mcp.list_prompts()
    names = {p.name for p in prompts}
    assert names == {
        "analyze_session",
        "find_files_modified",
        "compare_sessions",
        "start_and_watch",
    }


async def test_analyze_session_renders():
    mcp = FastMCP("test")
    register_prompts(mcp)
    res = await mcp.get_prompt("analyze_session", {"session_id": "abc-123"})
    text = " ".join(
        m.content.text if hasattr(m.content, "text") else str(m.content)
        for m in res.messages
    )
    assert "abc-123" in text
    assert "summarize_session" in text


async def test_find_files_modified_with_pattern():
    mcp = FastMCP("test")
    register_prompts(mcp)
    res = await mcp.get_prompt(
        "find_files_modified", {"session_id": "s1", "path_pattern": "AppData"}
    )
    text = " ".join(
        m.content.text if hasattr(m.content, "text") else str(m.content)
        for m in res.messages
    )
    assert "AppData" in text


async def test_start_and_watch_iterations():
    mcp = FastMCP("test")
    register_prompts(mcp)
    res = await mcp.get_prompt(
        "start_and_watch", {"exe_path": "C:/x.exe", "duration_seconds": "30"}
    )
    text = " ".join(
        m.content.text if hasattr(m.content, "text") else str(m.content)
        for m in res.messages
    )
    # 30 // 5 = 6 iterations.
    assert "6 iterations" in text
    assert "C:/x.exe" in text


async def test_compare_sessions_renders():
    mcp = FastMCP("test")
    register_prompts(mcp)
    res = await mcp.get_prompt(
        "compare_sessions", {"session_a": "A", "session_b": "B"}
    )
    text = " ".join(
        m.content.text if hasattr(m.content, "text") else str(m.content)
        for m in res.messages
    )
    assert "A" in text and "B" in text

"""MCP prompts that orchestrate multi-tool investigations."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Bind canned investigation prompts onto the FastMCP server."""

    @mcp.prompt(
        name="analyze_session",
        description="Investigate a tracker session and produce a forensic summary.",
    )
    def analyze_session(session_id: str) -> str:
        return (
            f"Use the activity-tracker MCP tools to analyze session {session_id}.\n\n"
            f"Steps:\n"
            f"1. Call get_session(session_id={session_id!r}) to confirm it exists "
            f"and check capture state.\n"
            f"2. Call summarize_session(session_id={session_id!r}) for a "
            f"high-level rollup.\n"
            f"3. Call query_events with kind='registry' to identify persistence "
            f"(Run/RunOnce keys, services).\n"
            f"4. Call query_events with kind='network' to spot outbound "
            f"connections.\n"
            f"5. Call search_events with q='AppData' / q='Temp' / q='Roaming' "
            f"to find data drops.\n"
            f"6. Produce a concise report classifying activity (benign install / "
            f"network exfil / persistence / lateral movement) with citations to "
            f"specific events."
        )

    @mcp.prompt(
        name="find_files_modified",
        description="List file write/delete/rename events for a session, optionally filtered by path pattern.",
    )
    def find_files_modified(
        session_id: str, path_pattern: str | None = None
    ) -> str:
        scope = f", filtering by '{path_pattern}'" if path_pattern else ""
        q_arg = repr(path_pattern) if path_pattern else "''"
        return (
            f"Find files modified by session {session_id}{scope}.\n\n"
            f"Use search_events(session_id={session_id!r}, q={q_arg}, "
            f"kind='file') and list the operations grouped by parent directory."
        )

    @mcp.prompt(
        name="compare_sessions",
        description="Diff two tracker sessions: kind histograms, paths unique to each, common parent processes.",
    )
    def compare_sessions(session_a: str, session_b: str) -> str:
        return (
            f"Compare sessions {session_a} and {session_b} using "
            f"summarize_session for both, then query specific kinds where the "
            f"histograms differ. Report: unique paths per session, common "
            f"pids/parents, kind delta."
        )

    @mcp.prompt(
        name="start_and_watch",
        description="Start a new session for an exe, tail for N seconds, summarize, and stop.",
    )
    def start_and_watch(exe_path: str, duration_seconds: int = 60) -> str:
        iters = max(1, int(duration_seconds) // 5)
        return (
            f"Track {exe_path} for {duration_seconds} seconds:\n\n"
            f"1. Call start_session(exe_path={exe_path!r}) — note the returned "
            f"session_id.\n"
            f"2. Loop: call tail_events(session_id, max_wait_seconds=5) until "
            f"{duration_seconds} seconds elapsed (~{iters} iterations).\n"
            f"3. Call summarize_session(session_id).\n"
            f"4. Call stop_session(session_id).\n"
            f"5. Report what the program did."
        )

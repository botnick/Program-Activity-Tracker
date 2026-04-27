# activity-tracker-mcp

Standalone MCP (Model Context Protocol) server that exposes the Activity Tracker's HTTP API to Claude Code / Claude Desktop. Talks HTTP only — never imports the tracker's modules — so it can run from anywhere as long as the backend is reachable.

## Install

From repo root:

```cmd
python -m pip install -e ".\mcp[dev]"
```

This installs `mcp[cli]>=1.2`, `httpx>=0.27`, `pydantic>=2.13`, `pydantic-settings>=2.6`. Console script `mcp-tracker` is registered.

## Run (manual)

```cmd
python -m mcp_tracker
```

stdio transport. Logs go to **stderr only** (stdio MCP requires clean stdout for JSON-RPC framing).

## Claude Code

`.mcp.json` is already at the repo root. Open the project in Claude Code, then `/mcp` lists the 14 activity-tracker tools.

## Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "activity-tracker": {
      "command": "python",
      "args": ["-m", "mcp_tracker"],
      "env": { "MCP_TRACKER_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

If you have multiple Pythons, point `command` at the venv's `python.exe` explicitly.

## Tools (14)

| # | Name | Purpose |
|---|---|---|
| 1 | `get_health` | enriched health (admin, uptime, capture stats, log dir) |
| 2 | `list_processes` | running OS processes (with optional `name_contains`) |
| 3 | `list_sessions` | all tracker sessions |
| 4 | `get_session` | one session by id |
| 5 | `start_session` | start tracking by `pid` or `exe_path` |
| 6 | `stop_session` | stop a session |
| 7 | `query_events` | filter + paginate (cursor-based) |
| 8 | `search_events` | substring search across path/target/operation/details |
| 9 | `tail_events` | poll-based live tail with `max_wait_seconds` |
| 10 | `export_session` | streaming CSV/JSONL → `~/Downloads` |
| 11 | `get_capture_stats` | per-session ETW stats from `/api/health` |
| 12 | `emit_event` | inject annotation event (gated behind `MCP_TRACKER_ALLOW_EMIT=1`) |
| 13 | `summarize_session` | client-side rollup: kind histogram, top paths, pids, time bounds |
| 14 | `get_metrics` | raw Prometheus metrics |

## Resources (6)

URI-addressable read-only:

- `tracker://health`
- `tracker://sessions`
- `tracker://sessions/{session_id}`
- `tracker://sessions/{session_id}/events?limit=200`
- `tracker://sessions/{session_id}/summary` (5 s TTL cache)
- `tracker://processes`

## Prompts (4)

User-invocable templates:

- `analyze_session(session_id)` — forensic classification
- `find_files_modified(session_id, path_pattern?)` — write/delete/rename grouped by directory
- `compare_sessions(session_a, session_b)` — diff kinds + paths + parents
- `start_and_watch(exe_path, duration_seconds=60)` — start → tail → summarize → stop

## Environment variables

Prefix `MCP_TRACKER_`:

| Var | Default | Purpose |
|---|---|---|
| `MCP_TRACKER_URL` | `http://127.0.0.1:8000` | tracker backend URL |
| `MCP_TRACKER_TIMEOUT` | `10.0` | HTTP timeout seconds |
| `MCP_TRACKER_DOWNLOAD_DIR` | `~/Downloads` | export destination |
| `MCP_TRACKER_ALLOW_EMIT` | `0` | gate `emit_event` tool (`1` to enable) |
| `MCP_TRACKER_TOKEN` | empty | bearer token (plumbed but unused — for future LAN use) |
| `MCP_TRACKER_LOG_LEVEL` | `INFO` | written to stderr only |

## Tests

```cmd
cd mcp
python -m pytest tests -v
```

40 tests: unit tests with `respx` mocks per tool/resource/prompt, plus integration tests via `httpx.ASGITransport` (no subprocess uvicorn needed).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Tracker is not reachable at <url>` | start the backend (`start.bat` at repo root) |
| `No session with id …` | call `list_sessions` first |
| `/metrics` returns 501 | `prometheus-client` not installed (it should be from `pyproject.toml`) |
| Tool calls fail silently in Claude Desktop | look in stderr — Claude shows it; or check `tracker_*` not registered: confirm `claude_desktop_config.json` syntax |

## Example Claude prompts

- "Use activity-tracker to summarize what xdt.exe wrote to AppData."
- "Compare session A and B, list paths unique to each."
- "Export session 78389686 as CSV."
- "List the top 10 paths Notepad touched in the last 30 seconds."

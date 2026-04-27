# activity-tracker-mcp

A standalone MCP (Model Context Protocol) server that exposes the
[Activity Tracker](../) HTTP API to MCP-aware clients such as Claude Code and
Claude Desktop. With it installed, an LLM agent can list running processes,
start a tracker session, query / search / tail captured events, export them to
disk, and run canned forensic analyses without touching the tracker UI.

## What it is

This server is a thin async wrapper around the tracker's REST API:

- **14 tools** for read/write operations (sessions, events, exports, metrics, ...).
- **6 resources** (3 static + 3 templated) for read-only structured snapshots.
- **4 prompts** that orchestrate multi-step investigations.

Transport is stdio (the default for `python -m mcp_tracker`), which is what
Claude Code's `.mcp.json` and Claude Desktop's `claude_desktop_config.json`
both expect.

## Install

From the repo root:

```bash
python -m pip install -e ./mcp[dev]
```

This installs the `activity-tracker-mcp` distribution (project name) which
provides the `mcp_tracker` import package.

If `mcp[cli]` cannot be installed (the SDK ships frequent API breaks), drop the
`[cli]` extra: `python -m pip install -e ./mcp` — the server itself only
imports `mcp.server.fastmcp.FastMCP`, which is part of the base package.

## Run

```bash
python -m mcp_tracker
```

The server speaks MCP over stdio (stdout/stdin); logs go to stderr.

The tracker backend must be running separately:

```bash
python -m uvicorn backend.app.main:app --port 8000
# or for ETW capture:
.\run-elevated.ps1
```

## Tools

| Tool | Purpose |
|------|---------|
| `get_health` | Tracker health, admin status, uptime, captures stats |
| `list_processes` | Running OS processes, optional substring filter |
| `list_sessions` | All tracker sessions (live + stopped) |
| `get_session` | Single session by id |
| `start_session` | Start tracking a process by pid OR exe_path |
| `stop_session` | Stop a running session |
| `query_events` | Page events with `kind`/`pid`/`since`/`until` filters and a base64 cursor |
| `search_events` | Substring search across path/target/operation/details |
| `tail_events` | Briefly poll for new events on a live session |
| `export_session` | Stream events to a CSV/JSONL file in `~/Downloads` |
| `get_capture_stats` | Per-session ETW capture stats from `/api/health` |
| `emit_event` | Inject an annotation event (gated by `MCP_TRACKER_ALLOW_EMIT`) |
| `summarize_session` | Counts by kind, top 10 paths, unique pids, time bounds |
| `get_metrics` | Raw Prometheus text or `{disabled: true}` if disabled |

## Resources

Static URIs:

- `tracker://health`
- `tracker://sessions`
- `tracker://processes`

Templated URIs:

- `tracker://sessions/{session_id}` — single session
- `tracker://sessions/{session_id}/events` — latest 200 events
- `tracker://sessions/{session_id}/summary` — aggregate rollup, cached for 5 s

All responses are JSON text.

## Prompts

- `analyze_session(session_id)` — full forensic walk-through.
- `find_files_modified(session_id, path_pattern?)` — file ops grouped by parent.
- `compare_sessions(session_a, session_b)` — diff two session histograms.
- `start_and_watch(exe_path, duration_seconds?)` — track an exe for N seconds.

## Claude Desktop config

Edit `%APPDATA%\Claude\claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "activity-tracker": {
      "command": "python",
      "args": ["-m", "mcp_tracker"],
      "env": {
        "MCP_TRACKER_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

Restart Claude Desktop. The server will appear under the plug icon as
`activity-tracker`.

## Claude Code config

Claude Code reads `.mcp.json` from the repo root. This repo ships one:

```json
{
  "mcpServers": {
    "activity-tracker": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_tracker"],
      "env": {
        "MCP_TRACKER_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

Run `claude` from the repo root and answer "Yes" when prompted to enable the
server. Once enabled, `/mcp` lists the tools.

## Environment variables

All variables are prefixed with `MCP_TRACKER_`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_TRACKER_URL` | `http://127.0.0.1:8000` | Base URL of the tracker backend |
| `MCP_TRACKER_TIMEOUT` | `10.0` | HTTP timeout in seconds |
| `MCP_TRACKER_DOWNLOAD_DIR` | `~/Downloads` | Where `export_session` writes files |
| `MCP_TRACKER_ALLOW_EMIT` | `false` | Set to `1`/`true` to enable `emit_event` |
| `MCP_TRACKER_TOKEN` | _(empty)_ | Bearer token sent on every request, if set |
| `MCP_TRACKER_LOG_LEVEL` | `INFO` | Server log level (stderr only) |

A `.env` file in the working directory is also read.

## Troubleshooting

- **"Tracker is not reachable at this URL"** — the backend isn't running. Start
  it with `python -m uvicorn backend.app.main:app --port 8000` or
  `run-elevated.ps1`.
- **`capture: needs_admin` on every new session** — the backend wasn't launched
  as Administrator. Sessions are still created and queryable; ETW capture is
  disabled until you elevate.
- **`get_metrics` returns `{disabled: true}`** — `prometheus_client` isn't
  installed in the backend's environment. `pip install prometheus-client` and
  restart the backend.
- **`emit_event` always errors** — by design. Set
  `MCP_TRACKER_ALLOW_EMIT=1` in the server's environment (e.g. inside the
  `env` block of `.mcp.json`).

## Tests

```bash
python -m pytest mcp/tests -v
```

40 tests cover unit (respx mocks) and integration (in-process FastAPI via
`httpx.ASGITransport`) paths.

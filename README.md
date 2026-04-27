# Activity Tracker

Production-oriented Windows activity tracker: pick an executable, get a
durable, queryable stream of process / file / registry / network events
from ETW kernel providers.

## Architecture

| Component                | Role                                                                                |
|--------------------------|-------------------------------------------------------------------------------------|
| `backend/`               | FastAPI control plane: session CRUD, event ingest, WebSocket fan-out, SQLite store. |
| `service/`               | Windows capture layer: pywintrace ETW consumer, orphan-session sweeper.             |
| `ui/`                    | React 18 + Vite single-page app served by the backend at `/`.                       |
| `mcp/` (Phase 4)         | MCP server exposing the same data to LLM agents over JSON-RPC.                      |

See [`docs/architecture.md`](docs/architecture.md) for the wiring diagram
and concurrency model.

## Quickstart

### Prerequisites

- Windows 10 or newer (capture only works on Windows; the backend itself
  runs anywhere if you skip the ETW layer).
- Python 3.10+.
- Node 20+.

### One-shot install + launch

```powershell
powershell -ExecutionPolicy Bypass -File bootstrap.ps1
powershell -ExecutionPolicy Bypass -File run-elevated.ps1
```

`bootstrap.ps1` installs the backend in editable mode, runs `npm ci`,
builds the UI into `ui/dist/`, and (if present) installs the MCP
package. `run-elevated.ps1` re-launches itself with UAC and starts
uvicorn on `127.0.0.1:8000`.

Then open <http://127.0.0.1:8000>.

## Running for real (with ETW capture)

ETW kernel providers require Administrator. Use `run-elevated.ps1`
(prompts for UAC) or install the backend as a Windows service under
LocalSystem — see [`docs/operations.md`](docs/operations.md) for an
NSSM walkthrough.

## Running without admin

The backend still starts; sessions just come back tagged
`capture: needs_admin` and the capture thread is never started. The UI,
historical queries, persistence, exports, and the WebSocket fan-out for
already-captured sessions all keep working. This is the supported
"developer with no UAC token" mode.

## API summary

| Method | Path                                       | Purpose                                           |
|--------|--------------------------------------------|---------------------------------------------------|
| GET    | `/api/processes`                           | List running processes; reports `admin: bool`.    |
| POST   | `/api/sessions`                            | Create a session for a `pid` or `exe_path`.       |
| GET    | `/api/sessions`                            | List all sessions (live + historical).            |
| DELETE | `/api/sessions/{id}`                       | Stop a session and detach its capture service.    |
| GET    | `/api/sessions/{id}/events`                | Filtered, paginated event read.                   |
| GET    | `/api/sessions/{id}/export?format=jsonl`   | Streaming export (`jsonl` or `csv`).              |
| POST   | `/api/sessions/{id}/emit`                  | Inject a custom event (testing / integrations).   |
| WS     | `/ws/sessions/{id}`                        | Replay buffered history then tail new events.     |
| GET    | `/api/health`                              | Liveness + uptime + capture/subscriber gauges.    |
| GET    | `/metrics`                                 | Prometheus exposition.                            |
| GET    | `/`                                        | Serves `ui/dist/index.html`.                      |

## Configuration

All settings flow through `backend.app.config.Settings`, environment
variables with the `TRACKER_` prefix, or a `.env` file in the repo
root.

| Variable                            | Default                                 | Notes                                                    |
|-------------------------------------|-----------------------------------------|----------------------------------------------------------|
| `TRACKER_BIND_HOST`                 | `127.0.0.1`                             | Bind address. Don't change without reading threat model. |
| `TRACKER_PORT`                      | `8000`                                  |                                                          |
| `TRACKER_DB_PATH`                   | `events.db`                             | Relative paths resolve against the repo root.            |
| `TRACKER_EVENT_RING_SIZE`           | `50000`                                 | Per-session in-memory ring (events).                     |
| `TRACKER_SUBSCRIBER_QUEUE_SIZE`     | `4096`                                  | WS subscriber backpressure cap.                          |
| `TRACKER_FILE_OBJECT_CACHE_SIZE`    | `100000`                                | ETW FileObject -> path LRU.                              |
| `TRACKER_CORS_ORIGINS`              | `http://{127.0.0.1,localhost}:{8000,5173}` | Comma-separated when set via env.                     |
| `TRACKER_LOG_DIR`                   | `logs`                                  | Relative paths resolve against the repo root.            |
| `TRACKER_LOG_LEVEL`                 | `INFO`                                  |                                                          |
| `TRACKER_METRICS_ENABLED`           | `true`                                  | When false, `/metrics` returns 501.                      |

## Development

```bash
make bootstrap      # pip install -e .[dev] + npm ci + ui build
make dev            # uvicorn --reload (no admin; capture stays needs_admin)
make test           # pytest
make lint           # ruff + eslint
make format         # ruff format
make typecheck      # mypy + tsc --noEmit
make build          # ui only
make run-elevated   # delegates to PowerShell + UAC
make clean
```

There's no test suite for the UI yet; `make test` only runs Python tests.

## MCP server

Phase 4 of the project plan adds an MCP server under `mcp/` that wraps
the REST API for use by LLM agents. If `mcp/README.md` exists in your
checkout, follow it; otherwise the package is not yet wired up.

## Project layout

```
.
+-- backend/
|   +-- app/
|   |   +-- main.py           # FastAPI app factory
|   |   +-- api_routes.py     # REST + WebSocket
|   |   +-- store.py          # SessionStore (ring + SQLite + writer thread)
|   |   +-- observability.py  # logs, /metrics, /api/health, trace ids
|   |   +-- config.py         # pydantic-settings
|   |   +-- db/               # schema.sql + migrations
|   +-- requirements.txt
+-- service/
|   +-- capture_service.py    # CaptureService, CaptureTarget, is_admin
|   +-- etw_cleanup.py        # orphan ETW session sweep
+-- ui/
|   +-- src/                  # React + TypeScript SPA
|   +-- dist/                 # build output (committed-ignored)
+-- tests/                    # pytest suite (capture / store / observability / integration)
+-- docs/
|   +-- architecture.md
|   +-- operations.md
|   +-- threat-model.md
+-- mcp/                      # Phase 4: MCP server (optional)
+-- bootstrap.ps1             # one-shot setup
+-- run-elevated.ps1          # launch under UAC
+-- Makefile
+-- pyproject.toml
+-- README.md
```

## Threat model

Read [`docs/threat-model.md`](docs/threat-model.md). In one sentence:
**this is a single-user, single-host, localhost-only tool with no
authentication, and exposing it on a network is a footgun.** The threat
model document also lists the data-sensitivity rules around `events.db`
and exported event archives.

# Activity Tracker

Real-time Windows process activity tracker. Pick any running process (e.g. `xdt.exe`) and watch every file open / read / write / delete, every registry key/value change, every TCP/UDP connection — and every descendant it spawns — stream live into a web UI. No DLL injection, no API hooks; pure ETW kernel observation, same level of visibility as Procmon / Sysmon.

```
┌─────────────────┐     ETW      ┌──────────────────────┐    JSON    ┌──────────────┐
│ target.exe      │ ───events───▶│ tracker_capture.exe  │ ──stdout──▶│ FastAPI      │
│  + descendants  │   (kernel)   │  (native C++)        │            │  + SQLite    │
└─────────────────┘              └──────────────────────┘            └──────┬───────┘
                                                                            │ WebSocket
                                                                            ▼
                                                                     ┌──────────────┐
                                                                     │ React UI     │
                                                                     │ /metrics     │
                                                                     │ MCP server   │──▶ Claude
                                                                     └──────────────┘
```

## What you get

- **Every path on every drive**: `C:\`, `D:\`, USB sticks, network shares (`\\server\share`). Drive letters resolved dynamically at startup via `QueryDosDeviceW`.
- **Realtime UI**: virtualized table, rAF-batched ingestion (smooth at 1000+ events/sec), drawer detail view, CSV/JSONL export, per-kind sparkline.
- **Process picker with real Windows icons** for every running .exe.
- **Five log streams** (`events`, `requests`, `errors`, `native`, `tracker`) viewable + tailable inside the UI.
- **MCP server** (`activity-tracker-mcp`) so Claude Code / Claude Desktop can query, summarize, and export sessions via 14 tools, 6 resources, 4 prompts.
- **SQLite WAL persistence**: sessions and events survive backend restarts; 30-day automatic retention sweep.
- **Native-only ETW backend**: no Python ETW fallback to drift; `pywintrace` removed in Phase 9.

## Two builds: release vs dev

This repo ships in two flavours. **End users want the release zip.** **Contributors want the full source.**

| | Release zip (end user) | Dev / source (this repo) |
|---|---|---|
| What you need | only Python 3.10+ | Python 3.10+, Node 20+, Visual Studio 2022+ with C++ workload, CMake, Ninja |
| Files in folder | `start.bat`, `stop.bat`, `requirements.txt`, `README.txt`, pre-built `tracker_capture.exe`, pre-built `ui/dist/`, Python source | full repo: C++ source, UI source, tests, bench, docs, CI, build scripts |
| First-run time | ~30 seconds (pip only) | ~5 minutes (compiles native binary + builds UI) |
| Use case | install on any Windows PC and just run | hacking on the code |
| Where to get it | GitHub Releases (auto-built by `.github/workflows/release.yml`) | `git clone` |

To produce a release zip locally from this repo:

```cmd
pwsh -ExecutionPolicy Bypass -File scripts\build-release.ps1
:: -> release\ActivityTracker-v0.2.0\  +  release\ActivityTracker-v0.2.0.zip
```

To cut a public release on GitHub: push a `vX.Y.Z` tag, `release.yml` runs on `windows-latest`, builds everything, and attaches the zip to a GitHub Release.

```cmd
git tag v0.2.0
git push origin v0.2.0
```

## Quick start (Windows, dev / source)

### Prerequisites

| | Minimum | Used for |
|---|---|---|
| Windows | 10 / 11 (x64) | ETW kernel providers |
| Python | 3.10 | backend + MCP server |
| Node.js | 20 | UI build (one-time) |
| Visual Studio | 2022 / 2026 with C++ workload | native ETW binary build (one-time) |
| Administrator | required | ETW capture sessions |

### One-click launch

Double-click **`start.bat`** at the repo root. The script:

1. Self-elevates via UAC.
2. Installs Python deps (first run only).
3. Builds the native binary via `vswhere` + CMake (first run only).
4. Builds the UI via `npm` (first run only).
5. Starts the backend on `http://127.0.0.1:8000`.
6. Opens the browser.

When you see `admin: yes` (green pill, top-right) you're ready. Pick a process from the left column → events stream live.

### One-time Defender exclusion (recommended)

ETW monitoring binaries are commonly flagged by AV. Add an exclusion once:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-defender-exclusion.ps1
```

The script self-elevates and registers `service\native\build` + `tracker_capture.exe`. Optional — skip if Defender is disabled.

## Portability — install on another PC

The repo is fully self-contained. To clone-and-run on a fresh Windows machine:

```cmd
git clone <repo-url> C:\path\to\activity-tracker
cd C:\path\to\activity-tracker
:: Install prerequisites listed above
start.bat
```

`start.bat` builds everything from source on first run. Nothing references the original repo's path; `BASE_DIR` is computed from `__file__` at runtime, the device map for path translation is built dynamically, and CMake / npm / pip pull all artifacts locally.

For pinned reproducibility:

```cmd
python -m pip install -r requirements-lock.txt
```

## Repository layout

```
activity-tracker/
├── start.bat / stop.bat / run-elevated.ps1   # one-click launchers
├── bootstrap.ps1                             # full install + build
├── scripts/setup-defender-exclusion.ps1      # one-time AV exclusion
├── pyproject.toml / requirements-lock.txt    # Python deps
│
├── backend/app/                              # FastAPI control plane
│   ├── main.py                               # app factory + middleware wiring
│   ├── api_routes.py                         # REST + WebSocket router
│   ├── store.py                              # SQLite WAL store + EventHub
│   ├── observability.py                      # logging, /metrics, /api/health
│   ├── icons.py                              # SHGetFileInfoW → PNG
│   ├── config.py                             # pydantic-settings
│   └── db/                                   # schema.sql + migrations runner
│
├── service/                                  # capture layer
│   ├── capture_service.py                    # thin Python orchestrator
│   └── native/                               # C++ ETW engine
│       ├── CMakeLists.txt
│       ├── src/                              # ETW session, TDH parser, etc.
│       └── resources/                        # icon + .rc + regen script
│
├── ui/                                       # React 18 + TypeScript + Vite 6
│   ├── public/favicon.ico
│   └── src/                                  # components + hooks
│
├── mcp/                                      # standalone MCP server package
│   └── src/mcp_tracker/                      # FastMCP tools/resources/prompts
│
├── tests/ + bench/                           # 99 backend + MCP tests, throughput bench
├── docs/                                     # architecture, operations, threat-model, risks-th, manual-th
└── CLAUDE.md                                 # guide for future Claude Code instances
```

## API summary

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | enriched: admin, uptime, capture stats, log dir |
| `GET` | `/api/processes` | snapshot of running processes (native first, psutil fallback) |
| `GET` | `/api/processes/icon?exe=` | extracted Windows icon as PNG, cached |
| `POST` | `/api/sessions` | start tracking by `pid` or `exe_path` |
| `DELETE` | `/api/sessions/{id}` | stop a session |
| `GET` | `/api/sessions` | list sessions |
| `GET` | `/api/sessions/{id}/events?kind=&pid=&since=&until=&q=&limit=&offset=` | filter + paginate |
| `GET` | `/api/sessions/{id}/export?format=csv\|jsonl` | streaming download |
| `POST` | `/api/sessions/{id}/emit` | inject custom annotation event |
| `WS` | `/ws/sessions/{id}` | live event stream |
| `GET` | `/api/logs/streams` | list log streams |
| `GET` | `/api/logs/{stream}?tail=N` | last N lines |
| `WS` | `/ws/logs/{stream}` | live log tail |
| `GET` | `/metrics` | Prometheus text |
| `GET` | `/` | UI |
| `GET` | `/favicon.ico` | UI favicon |

## Configuration

Every knob honors `TRACKER_*` environment variables (`pydantic-settings`). Selected ones:

| Variable | Default | Purpose |
|---|---|---|
| `TRACKER_BIND_HOST` | `127.0.0.1` | bind address (do not expose to LAN — no auth) |
| `TRACKER_PORT` | `8000` | port |
| `TRACKER_DB_PATH` | `events.db` | SQLite path (relative → repo root) |
| `TRACKER_DB_RETENTION_DAYS` | `30` | drop events older than N days; `0` disables |
| `TRACKER_FILE_OBJECT_CACHE_SIZE` | `100000` | LRU cap for FileObject→path map |
| `TRACKER_LOG_DIR` | `logs` | log directory |
| `TRACKER_LOG_LEVEL` | `INFO` | root log level |

Set in CMD before launch: `set TRACKER_DB_RETENTION_DAYS=7 && start.bat`.

## Development

```cmd
make test            :: pytest backend + MCP suites
make lint            :: ruff + eslint
make typecheck       :: mypy + tsc
make build           :: vite build
make dev             :: uvicorn --reload (non-admin: capture sessions return needs_admin)
make run-elevated    :: same as start.bat
```

`bench/throughput.py` measures end-to-end events/sec under a synthetic file workload. See `bench/README.md`.

## Documentation

| File | What it covers |
|---|---|
| `docs/manual-th.md` | full Thai user guide (install → daily use → troubleshooting → MCP) |
| `docs/architecture.md` | concurrency model + storage + diagram |
| `docs/operations.md` | running as a Windows service, Prometheus scraping, troubleshooting |
| `docs/threat-model.md` | trust boundaries, what attacks the design defends against |
| `docs/risks-th.md` | full risk register with mitigations (Thai) |

## License

Personal use. Not for redistribution.

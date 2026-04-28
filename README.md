# Activity Tracker — real-time Windows process monitor (ETW + web UI)

Lightweight, free, open-source alternative to Procmon. Pick any running Windows process and watch its file, registry, process, and network activity stream live into a browser. Pure ETW (no DLL injection, no hooks), single-binary capture engine in C++, FastAPI backend, React UI, and a built-in MCP server so AI clients (Claude Code / Claude Desktop / Cursor / Continue / Cline / Windsurf / Goose) can query and summarise sessions.

**Use it for:** debugging "what is this exe doing", malware triage, detecting hidden file writes, IO profiling, watching a child process tree, integrating live activity into AI-assisted workflows.

**[Download the latest release →](https://github.com/botnick/Program-Activity-Tracker/releases)** (Windows 10/11 x64; no Python install required, just unzip and run `tracker.exe`)

```
target.exe + descendants ──ETW──▶ tracker_capture.exe ──stdout──▶ FastAPI + SQLite ──WS──▶ React UI
                                                                          └──HTTP──▶ MCP server ──▶ AI client
```

## Features

- **Every path on every drive** — `C:\`, `D:\`, USB, network shares (`\\server\share`). Drive map resolved at startup via `QueryDosDeviceW`.
- **Real-time web UI** — virtualised table, rAF-batched render (smooth at 1 000+ events/sec), CSV/JSONL export, per-kind sparkline, detail drawer.
- **Process picker** with the actual Windows icons.
- **Capture monitor in `tracker.exe`** — live CPU / RAM / threads / handles for the native binary, events-per-second sparkline, per-kind bar chart.
- **5 log streams** (`events`, `requests`, `errors`, `native`, `tracker`) tailable from inside the UI.
- **MCP server** — 14 tools, 6 resources, 4 prompts over stdio. The "MCP How-To" tab in the UI has copy-paste configs for every supported client.
- **SQLite WAL persistence** — sessions + events survive restarts; 30-day automatic retention sweep.
- **Native-only ETW backend** — single C++ binary, no Python ETW fallback, no API hooks, no driver.

## Two builds: release vs dev

The repo ships in two flavours. **End users grab the release zip.** **Contributors clone the source.**

| | Release zip (end user) | Dev / source (this repo) |
|---|---|---|
| What you need | nothing — just Win 10/11 + admin | Python 3.10+, Node 20+, Visual Studio 2022+ (C++), CMake, Ninja |
| Entry point | `tracker.exe` (Tk GUI launcher) | `start.bat` |
| Files in folder | `tracker.exe`, `python/` (bundled embedded interpreter + all deps), `backend/`, `service/native/build/tracker_capture.exe`, `ui/dist/`, `mcp/`, `.mcp.json`, `README.txt` | full source: C++, React TS, tests, bench, docs, CI |
| Bundled Python? | yes | no — uses system Python |
| First-run time | ~5 s (no pip, no compile) | ~5 min (compiles native binary + builds UI) |
| Where to get it | [GitHub Releases](https://github.com/botnick/Program-Activity-Tracker/releases) (auto-built by `.github/workflows/release.yml`) | `git clone` |

The release zip is **self-contained**: download → extract → run `tracker.exe`. No Python install on the user's machine, no internet on first run, no `.bat` files at all — `tracker.exe` is the only thing the user clicks.

### Producing a release zip

Locally (requires Python + Node + VS for the prerequisite builds):

```cmd
pwsh -ExecutionPolicy Bypass -File scripts\build-release.ps1
:: → release\ActivityTracker-vX.Y.Z\  +  release\ActivityTracker-vX.Y.Z.zip
:: (omits bundled Python and tracker.exe; for a full release, use the CI path below)
```

Public release on GitHub — push a `vX.Y.Z` tag and let CI do the heavy lifting:

```cmd
git tag v0.2.1
git push origin v0.2.1
```

`release.yml` on `windows-latest` then:
1. Builds `tracker_capture.exe` (cmake + VS 2022).
2. Builds `ui/dist/` (`npm ci` + `npm run build`).
3. Downloads `python-3.12.7-embed-amd64.zip`, patches `python312._pth` so `..` is on sys.path, bootstraps pip, and installs the runtime requirements + the `mcp_tracker` package into the embedded interpreter.
4. Runs PyInstaller against `launcher/launcher.spec` to produce `tracker.exe` (UAC-elevated, embedded `tracker.ico`, ~30 MB).
5. Calls `scripts/build-release.ps1 -SkipBuild -PythonEmbedDir … -LauncherExe …` to assemble the folder + zip.
6. Attaches the zip to a GitHub Release.

The `.exe` is **never committed** to the repo — only `launcher/tracker_launcher.py` and `launcher/launcher.spec` are. CI builds the binary fresh on every tag.

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
├── start.bat / stop.bat / run-elevated.ps1   # one-click dev launchers (NOT shipped in release zip)
├── bootstrap.ps1                             # full install + build (dev)
├── launcher/
│   ├── tracker_launcher.py                   # Tk GUI replacement for start.bat / stop.bat
│   └── launcher.spec                         # PyInstaller spec → tracker.exe (CI-built)
├── scripts/
│   ├── build-release.ps1                     # assemble release/<name>/ + .zip
│   ├── release-template/                     # README.txt + requirements.txt for the release
│   └── setup-defender-exclusion.ps1          # one-time AV exclusion
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

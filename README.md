# Activity Tracker — real-time Windows process monitor (ETW + web UI)

Lightweight, free, open-source alternative to Procmon. Pick any running Windows process and watch its file, registry, process, and network activity stream live into a browser. Pure ETW (no DLL injection, no hooks), single-binary capture engine in C++, FastAPI backend, React UI, and a built-in MCP server so AI clients (Claude Code / Claude Desktop / Cursor / Continue / Cline / Windsurf / Goose) can query and summarise sessions.

**Use it for:** debugging "what is this exe doing", malware triage, detecting hidden file writes, IO profiling, watching a child process tree, integrating live activity into AI-assisted workflows.

**[Download the latest release →](https://github.com/botnick/Program-Activity-Tracker/releases)** — Windows 10/11 x64. No Python install, no compiler, no internet on first run. Just unzip and double-click `tracker.exe`.

```
target.exe + descendants ──ETW──▶ tracker_capture.exe ──stdout──▶ FastAPI + SQLite ──WS──▶ React UI
                                                                          └──HTTP──▶ MCP server ──▶ AI client
```

## Quick start

1. Download `ActivityTracker-vX.Y.Z.zip` from the [Releases page](https://github.com/botnick/Program-Activity-Tracker/releases).
2. Extract anywhere (e.g. `C:\Tools\ActivityTracker\`).
3. Right-click `tracker.exe` → **Run as administrator** (or double-click and accept the UAC prompt).
4. Click **▶ Start** in the launcher. The browser opens at `http://127.0.0.1:8000` once the backend is ready.
5. Pick a process from the picker → click **Start capture**.

To stop everything cleanly: click **■ Stop** or close the launcher window. The launcher kills `tracker_capture.exe` and any stray ETW sessions on its way out.

> **Optional one-time Defender exclusion** (the ETW capture binary occasionally trips Defender): run `scripts\setup-defender-exclusion.ps1` as admin from inside the extracted folder.

## Features

- **Every path on every drive** — `C:\`, `D:\`, USB, network shares (`\\server\share`). Drive map resolved at startup via `QueryDosDeviceW`.
- **Real-time web UI** — virtualised table, rAF-batched render (smooth at 1 000+ events/sec), CSV/JSONL export, per-kind sparkline, detail drawer.
- **Process picker** with the actual Windows icons.
- **Capture monitor in `tracker.exe`** — live CPU / RAM / threads / handles for the native binary, events-per-second sparkline, per-kind bar chart.
- **5 log streams** (`events`, `requests`, `errors`, `native`, `tracker`) tailable from inside the UI.
- **MCP server** — 14 tools, 6 resources, 4 prompts over stdio. The "MCP How-To" tab in the UI has copy-paste configs for every supported client.
- **SQLite WAL persistence** — sessions + events survive restarts; 30-day automatic retention sweep.
- **Native-only ETW backend** — single C++ binary, no Python ETW fallback, no API hooks, no driver.

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

Every knob honours `TRACKER_*` environment variables (`pydantic-settings`). Selected ones:

| Variable | Default | Purpose |
|---|---|---|
| `TRACKER_BIND_HOST` | `127.0.0.1` | bind address (do not expose to LAN — no auth) |
| `TRACKER_PORT` | `8000` | port |
| `TRACKER_DB_PATH` | `events.db` | SQLite path (relative → release folder) |
| `TRACKER_DB_RETENTION_DAYS` | `30` | drop events older than N days; `0` disables |
| `TRACKER_FILE_OBJECT_CACHE_SIZE` | `100000` | LRU cap for FileObject→path map |
| `TRACKER_LOG_DIR` | `logs` | log directory |
| `TRACKER_LOG_LEVEL` | `INFO` | root log level |

Set in `cmd` before launching `tracker.exe`, e.g. `set TRACKER_DB_RETENTION_DAYS=7`. For a permanent change use System Properties → Environment Variables.

## MCP server (use with AI clients)

The release zip ships an `mcp/` folder + `.mcp.json`; the bundled Python has `mcp_tracker` already installed. Open the **MCP How-To** tab in the web UI for copy-paste config snippets covering Claude Code, Claude Desktop, Cursor, Continue, Cline, Windsurf, Goose, MCP Inspector, and any generic MCP-stdio client. The backend (`tracker.exe`) must be running for tool calls to succeed.

## Building from source

For contributors only — end users should use the [release zip](https://github.com/botnick/Program-Activity-Tracker/releases).

**Prerequisites:** Python 3.10+, Node 20+, Visual Studio 2022+ with C++ workload, CMake, Ninja, Administrator.

```cmd
git clone https://github.com/botnick/Program-Activity-Tracker
cd Program-Activity-Tracker
start.bat
:: ↑ self-elevates via UAC, installs Python deps, builds the native binary
::   via cmake, builds the UI via npm, runs uvicorn at 127.0.0.1:8000.
::   Dev only — the release zip ships tracker.exe and contains no .bat files.
```

Other dev commands:

```cmd
make test            :: pytest backend + MCP suites
make lint            :: ruff + eslint
make typecheck       :: mypy + tsc
make build           :: vite build (writes ui/dist/)
make dev             :: uvicorn --reload (non-admin → capture sessions return needs_admin)
```

`bench/throughput.py` measures end-to-end events/sec under a synthetic file workload (see `bench/README.md`).

### Producing a release zip

A public GitHub Release is auto-built on every `vX.Y.Z` tag — push the tag and the workflow does the rest:

```cmd
git tag v0.2.1
git push origin v0.2.1
```

`.github/workflows/release.yml` on `windows-latest` then:
1. Builds `tracker_capture.exe` (cmake + VS 2022).
2. Builds `ui/dist/` (`npm ci` + `npm run build`).
3. Downloads `python-3.12.7-embed-amd64.zip`, patches `python312._pth` (adds `..` and uncomments `import site`), bootstraps pip, installs the runtime requirements + `mcp_tracker` into the embedded interpreter.
4. Runs PyInstaller against `launcher/launcher.spec` to produce `tracker.exe` (UAC-elevated, embedded `tracker.ico`, ~30 MB).
5. Calls `scripts/build-release.ps1 -SkipBuild -PythonEmbedDir … -LauncherExe …` to assemble `release/ActivityTracker-vX.Y.Z/` + `.zip`.
6. `softprops/action-gh-release@v2` attaches the zip to a GitHub Release.

To produce a local **partial** zip (no bundled Python, no `tracker.exe` — for dev smoke-testing only):

```cmd
pwsh -ExecutionPolicy Bypass -File scripts\build-release.ps1
:: → release\ActivityTracker-vX.Y.Z\  +  release\ActivityTracker-vX.Y.Z.zip
```

`tracker.exe` and `tracker_capture.exe` are **never committed** to the repo. CI builds them fresh on every release run.

## Repository layout

```
activity-tracker/
├── start.bat / stop.bat                       # dev one-click launchers (NOT in release zip)
├── launcher/
│   ├── tracker_launcher.py                    # Tk GUI source — built into release/tracker.exe by CI
│   └── launcher.spec                          # PyInstaller spec
├── scripts/
│   ├── build-release.ps1                      # assemble release/<name>/ + .zip
│   ├── release-template/                      # README.txt + requirements.txt for the release
│   └── setup-defender-exclusion.ps1           # one-time AV exclusion
├── pyproject.toml / requirements-lock.txt     # Python deps
│
├── backend/app/                               # FastAPI control plane
│   ├── main.py / api_routes.py / store.py
│   ├── observability.py                       # logging, /metrics, /api/health
│   ├── icons.py                               # SHGetFileInfoW → PNG
│   ├── config.py                              # pydantic-settings
│   └── db/                                    # schema.sql + migrations runner
│
├── service/                                   # capture layer
│   ├── capture_service.py                     # Python ↔ native subprocess bridge
│   └── native/                                # C++ ETW engine
│       ├── CMakeLists.txt
│       ├── src/                               # ETW session, TDH parser, path translator
│       └── resources/                         # icon + .rc
│
├── ui/                                        # React 18 + TypeScript + Vite 6
│   └── src/                                   # App.tsx (Events / Logs / MCP How-To), components, hooks
│
├── mcp/                                       # standalone MCP server package
│   └── src/mcp_tracker/                       # FastMCP tools / resources / prompts
│
├── tests/ + bench/                            # 99 backend + MCP tests, throughput bench
├── docs/                                      # architecture, operations, threat-model, risks-th, manual-th
├── .github/workflows/                         # ci.yml (lint + test) + release.yml (auto-release on tag)
├── README.md                                  # this file
└── CLAUDE.md                                  # internal architecture / invariants reference
```

## Documentation

| File | What it covers |
|---|---|
| `docs/manual-th.md` | full Thai user guide (install → daily use → MCP → troubleshooting) |
| `docs/architecture.md` | concurrency model + storage + diagram |
| `docs/operations.md` | running as a Windows service, Prometheus scraping, troubleshooting |
| `docs/threat-model.md` | trust boundaries + what attacks the design defends against |
| `docs/risks-th.md` | full risk register with mitigations (Thai) |

## License

Personal use. Not for redistribution.

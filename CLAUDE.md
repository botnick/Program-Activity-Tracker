# CLAUDE.md

Guide for Claude Code instances working in this repository.

## Project

Real-time Windows process activity tracker: pick a target process, stream every file / registry / process / network event from the kernel into a web UI. ETW-based, same visibility as Procmon. Single-user, localhost-only, not redistributed.

Tech stack: native C++ ETW engine (CMake build), Python FastAPI control plane, React+Vite UI, optional MCP server for Claude integration.

## Architecture

```
target.exe (any process tree)
  ↓ ETW kernel events (4 manifest providers)
service/native/build/tracker_capture.exe   (C++17, ~600 LOC, /W4 clean)
  ↓ NDJSON over stdout (hello sentinel + events + heartbeat)
service/capture_service.py                  (~370 LOC, thin subprocess wrapper)
  ↓ on_event callback, run_coroutine_threadsafe
backend/app/                                 (FastAPI)
  ├── store.py        SQLite WAL + ring buffer + writer thread + retention
  ├── api_routes.py   REST + WebSocket
  ├── observability.py 4 log streams + /metrics + /api/health + RequestTraceMiddleware
  ├── icons.py        SHGetFileInfoW → PNG (ctypes, no Pillow)
  └── main.py         FastAPI factory; CORS + trace middleware + lifespan hooks
  ↓ WebSocket /ws/sessions/{id}, REST GET/POST
ui/src/  (React 18, Tailwind 3, virtualized via @tanstack/react-virtual)
  ├── App.tsx                 tab nav (Events | Logs)
  ├── hooks/useEventStream    rAF-batched ingestion (≤60 Hz renders at any rate)
  ├── hooks/useLogStream      live tail of any log stream
  ├── hooks/useProcessList    diff-update — array identity preserved for unchanged rows
  └── components/             ProcessPicker (real EXE icons), EventTable, EventDetailDrawer (slide), RateSparkline (1 Hz tick), LogsTab, ToastStack, ...
```

The MCP server (`mcp/`) is a standalone package that talks to the FastAPI HTTP surface — no shared imports.

## Components

- **`service/native/`** — C++17 ETW consumer built via CMake.
  - Subscribes to `Microsoft-Windows-Kernel-File / -Registry / -Process / -Network` with all relevant keywords.
  - Maintains a thread-safe LRU `FileObject → path` cache so Read/Write events resolve to filenames after Create.
  - `path_translator` builds a DOS-device map dynamically (A–Z + UNC + LanmanRedirector).
  - `pid_filter` expands the tracked PID set on every kernel ProcessStart whose ParentProcessID is already tracked.
  - Emits NDJSON: hello sentinel first, then events, then 1 Hz heartbeats.
  - Also has a `--list-processes` mode (Toolhelp32 + QueryFullProcessImageNameW + LookupAccountSidW) that the backend prefers over psutil.
  - Embedded icon (`resources/tracker.ico`) and version info via the `.rc` file.

- **`service/capture_service.py`** — thin Python wrapper. Spawns the native binary, validates the hello sentinel (version handshake), pumps stdout (events + heartbeat) and stderr (logs → `activity_tracker.native` logger). No ETW logic in Python.

- **`backend/app/`** — FastAPI app. All Phase 1+2+3 modules wired in `main.py`:
  - `SessionStore` is SQLite-WAL-backed; ring buffer in front of disk for live tail; batched writer thread; 30-day retention sweep configurable via `TRACKER_DB_RETENTION_DAYS`.
  - `EventHub` fans out to WebSocket subscribers; drop counter `hub.dropped_subscribers` is observable when slow consumers disconnect.
  - Observability: `RotatingFileHandler` per log stream (events, requests, errors, native, tracker), JSON formatter, trace-id contextvar, Prometheus metrics, enriched `/api/health`.

- **`ui/`** — React + Tailwind. Every component memoized; events flushed in `requestAnimationFrame` so render rate caps at the display refresh rate even at 1000+ events/sec.

- **`mcp/`** — standalone package `activity-tracker-mcp`. 14 tools / 6 resources / 4 prompts via `mcp.server.fastmcp.FastMCP`. Stdio transport. Configured via `.mcp.json` at repo root (Claude Code) or `claude_desktop_config.json` (Claude Desktop).

## Commands

Backend (run from repo root):
```cmd
python -m pip install -e ".[dev]"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Native binary (Visual Studio Developer Prompt):
```cmd
cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build service\native\build --config Release
```

UI (run from `ui/`):
```cmd
npm install
npm run build         :: writes ui/dist/ — required for the backend's "/" route
npm run dev           :: standalone dev server (Vite proxy is configured for /api + /ws)
```

MCP server (after `pip install -e ./mcp[dev]`):
```cmd
python -m mcp_tracker
```

End-to-end one-click: double-click **`start.bat`** at the repo root (self-elevates, builds everything, opens browser).

## Tests

```cmd
python -m pytest tests        :: backend (59 tests + 1 admin-skip)
python -m pytest mcp/tests    :: MCP server (40 tests)
python -m ruff check backend service tests bench
python -m mypy backend service          :: continue-on-error in CI
cd ui && npm run typecheck && npm run lint && npm run build
```

The admin-gated test (`tests/test_native_smoke_admin.py`) skips on non-admin shells. Run it from an elevated prompt to verify real ETW capture.

## Critical invariants

1. **Native binary is the sole ETW backend.** Phase 9 deleted pywintrace. If `tracker_capture.exe` is missing, `CaptureService.start()` raises with build instructions. `start.bat` auto-builds via `vswhere`.
2. **Filter is by PID, not by path.** Every path on every drive — AppData, Documents, D:\, network shares — is captured. The UI search box does client-side substring filtering only; never trim the underlying capture.
3. **Hello-sentinel handshake** between Python wrapper and C++ binary catches wire-format drift (`SUPPORTED_PROTOCOL_VERSION = "1.0"`). Bumping either side without the other fails `start()` cleanly.
4. **PID-reuse protection** via `OpenProcess` + `GetProcessTimes`: if a tracked PID is reused by an unrelated process, its events are dropped.
5. **Log streams are routed by logger name.** Don't add a new file handler ad-hoc; use `_attach_stream_handler(...)` in `observability.py`.
6. **`backend/app/main.py:BASE_DIR = parents[2]`** — moving `main.py` breaks UI / native binary path resolution. Same for `Path(__file__).resolve().parents[1]` in `service/capture_service.py`.
7. **CORS is locked to localhost origins only.** Do not relax `cors_origins()` without explicit user approval — there is no auth.
8. **DB retention sweep runs in the writer thread.** Don't add long-running DB ops there; they block the next batch flush.

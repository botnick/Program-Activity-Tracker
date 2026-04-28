# CLAUDE.md

Internal architecture, conventions, and invariants reference for contributors. Read this first before touching anything that crosses module boundaries.

## Project

Real-time Windows process activity tracker: pick a target process, stream every file / registry / process / network event from the kernel into a web UI. ETW-based, same visibility as Procmon. Single-user, localhost-only.

Tech stack: native C++ ETW engine (CMake build), Python FastAPI control plane, React+Vite UI, MCP (Model Context Protocol) bridge over stdio, Tk + PyInstaller GUI launcher (`tracker.exe`) for end users.

**Two delivery modes:**
- **Dev** — `git clone`, requires Python 3.10+ / Node 20+ / VS 2022 (C++) / CMake / Ninja. Entry point is `start.bat` at repo root.
- **Release zip** — auto-built by `.github/workflows/release.yml` on every `vX.Y.Z` tag; downloaded by end users; self-contained: bundled embeddable Python + all deps + native binary + UI + MCP. Entry point is `tracker.exe`. **No** `.bat` files inside the release zip.

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
  ├── App.tsx                 tab nav (Events | Logs | MCP How-To)
  ├── hooks/useEventStream    rAF-batched ingestion (≤60 Hz renders at any rate)
  ├── hooks/useLogStream      live tail of any log stream
  ├── hooks/useProcessList    diff-update — array identity preserved for unchanged rows
  └── components/             ProcessPicker (real EXE icons), EventTable, EventDetailDrawer (slide), RateSparkline (1 Hz tick), LogsTab, McpHowToTab (per-client config snippets), OperationsFilter, ToastStack, ...

launcher/  (Tk GUI, packaged into release/tracker.exe by PyInstaller)
  ├── tracker_launcher.py     replaces start.bat / stop.bat in the release zip
  │   - self-elevates via UAC; embedded uac_admin manifest
  │   - prefers <root>/python/python.exe (bundled embeddable interpreter)
  │   - generates per-launch secrets.token_urlsafe(32), injects
  │     TRACKER_AUTH_TOKEN env into uvicorn, opens browser at ?token=
  │     (UI hoists to localStorage, strips URL bar)
  │   - spawns uvicorn as a subprocess; pumps stdout into ANSI-coloured Text
  │   - auto-restart on unexpected exit: 1 s / 2 s / 4 s backoff, cap 3,
  │     streak resets on first successful /api/health
  │   - Capture monitor tab: psutil + /api/health + /metrics polled at 1 Hz;
  │     KPI grid (events/sec, total, tracked pids, file-cache, key-cache,
  │     CPU, RAM, threads), live sparklines, per-kind bar chart
  │   - Backend / Events / Errors / Native log tabs (file-tail + ANSI parser)
  │   - logman -ets for ETW orphan cleanup (mirror stop.bat)
  │   - background update check on startup; "vX.Y.Z available" badge in
  │     header on hit, silent on offline failure
  └── launcher.spec           PyInstaller one-file spec; uac_admin=True; embeds tracker.ico
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

- **`mcp/`** — standalone package `activity-tracker-mcp`. 14 tools / 6 resources / 4 prompt templates via `mcp.server.fastmcp.FastMCP`. Stdio transport. Configured via `.mcp.json` at the repo root for editor-style clients, or via the host's MCP server config file for desktop clients.

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

End-to-end one-click (DEV): double-click **`start.bat`** at the repo root (self-elevates, builds native + UI, runs uvicorn, opens browser). The release zip uses **`tracker.exe`** instead.

Release packaging (CI does this on every `vX.Y.Z` tag; can also run locally):
```cmd
:: Local — partial; requires Python + Node + VS prerequisites and skips bundled-Python step
pwsh -ExecutionPolicy Bypass -File scripts\build-release.ps1
:: → release\ActivityTracker-vX.Y.Z\  +  release\ActivityTracker-vX.Y.Z.zip

:: Public release — push a tag; .github/workflows/release.yml on windows-latest:
::   1. cmake build (tracker_capture.exe)
::   2. npm ci + npm run build (ui/dist)
::   3. download python-3.12.7-embed-amd64, patch _pth (`..` + `import site`),
::      bootstrap pip, install setuptools/wheel, install requirements.txt,
::      install ./mcp with --no-build-isolation
::   4. PyInstaller against launcher/launcher.spec → tracker.exe (UAC manifest)
::   5. build-release.ps1 -PythonEmbedDir python-embed -LauncherExe launcher/dist/tracker.exe
::   6. softprops/action-gh-release@v2 attaches the zip to the GitHub Release
git tag v0.2.1 && git push origin v0.2.1
```

The launcher .exe is **never committed** — only `launcher/tracker_launcher.py` and `launcher/launcher.spec` are. `*.exe` is in `.gitignore`.

## Tests

```cmd
python -m pytest tests        :: backend (66 tests + 1 admin-skip)
python -m pytest mcp/tests    :: MCP server (40 tests)
python -m ruff check backend service tests launcher bench
python -m mypy backend service          :: STRICT in CI — no continue-on-error
cd ui && npm run typecheck && npm run lint && npm run build
```

The admin-gated test (`tests/test_native_smoke_admin.py`) skips on non-admin shells. Run it from an elevated prompt to verify real ETW capture. `tests/test_auth_middleware.py` exercises the optional bearer-token gate without needing the native binary.

## Critical invariants

1. **Native binary is the sole ETW backend.** If `tracker_capture.exe` is missing, `CaptureService.start()` raises with build instructions. `start.bat` auto-builds via `vswhere`.
2. **Filter is by PID, not by path.** Every path on every drive — AppData, Documents, D:\, network shares — is captured. The UI search box does client-side substring filtering only; never trim the underlying capture.
3. **Hello-sentinel handshake** between Python wrapper and C++ binary catches wire-format drift (`SUPPORTED_PROTOCOL_VERSION = "1.0"`). Bumping either side without the other fails `start()` cleanly.
4. **PID-reuse protection** via `OpenProcess` + `GetProcessTimes`: if a tracked PID is reused by an unrelated process, its events are dropped.
5. **PID soft cap** (`PidFilter::kDefaultMaxPids = 500`). The native binary refuses to add new descendants past the cap and emits a one-shot stderr warning. Override with `--max-pids=N`.
6. **Log streams are routed by logger name.** Don't add a new file handler ad-hoc; use `_attach_stream_handler(...)` in `observability.py`.
7. **`backend/app/main.py:BASE_DIR = parents[2]`** — moving `main.py` breaks UI / native binary path resolution. Same for `Path(__file__).resolve().parents[1]` in `service/capture_service.py`.
8. **Lifespan, not `@app.on_event`.** Shutdown work belongs in the `lifespan` async context manager in `main.py`. FastAPI 0.116+ has deprecated `on_event`.
9. **Auth is opt-in.** `AuthMiddleware` is wired but `settings.auth_token` is empty by default. When set, the middleware exempts `/`, `/favicon.ico`, `/assets/*`, `/metrics`, `/api/health` (for SPA load + scrapers). The launcher generates a per-launch `secrets.token_urlsafe(32)`; honour an inherited `TRACKER_AUTH_TOKEN` so power users can pin a stable token. CORS still locks origins to localhost regardless.
10. **DB retention runs in its own thread.** Sweeps go through `_retention_loop` with its own SQLite connection (WAL allows concurrent writers across connections), so a multi-million-row DELETE no longer pauses event INSERTs. Don't put retention back inside `_writer_loop`.
11. **No long-running calls on the ETW consumer thread.** v0.2.5 regressed by calling `EnumerateOpenFiles()` synchronously in the event handler — system-wide handle scan blocked the consumer for ~200 ms, kernel ETW buffers filled, sessions died after 5–15 s. Keep `HandleEvent` and its callees O(1) per event. The FileObject + KeyObject caches are mutex-protected hash lookups (~1 µs); anything heavier needs to live on its own thread.
12. **No `.bat` files in the release zip.** `tracker.exe` (built by `release.yml`, never committed) is the only entry point users see. `start.bat` / `stop.bat` exist in the repo for dev convenience only.
13. **No `.exe` is committed.** `*.exe` is gitignored. CI builds `tracker_capture.exe` (cmake) and `tracker.exe` (PyInstaller) fresh on every release run.
14. **Embeddable Python ignores `PYTHONPATH`.** The `release.yml` step that bootstraps `python-embed/` MUST add `..` to `pythonXX._pth` so `backend.*` and `service.*` resolve when the bundled python runs uvicorn. Don't skip that step.
15. **`pyproject.toml` has no UTF-8 BOM.** `bump-and-release.ps1` writes via `[System.IO.File]::WriteAllLines` with `UTF8Encoding(false)` because PowerShell 5.1's `Set-Content -Encoding UTF8` adds a BOM and pip's tomli rejects it.
16. **Markdown stays in sync.** Whenever code, workflow, release pipeline, MCP surface, env vars, install path, or entry point changes, update `README.md` + `CLAUDE.md` + `mcp/README.md` + `docs/*.md` + `scripts/release-template/README.txt` in the same commit.

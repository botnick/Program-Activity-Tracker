# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Production-oriented Windows activity tracker scaffold. A user picks an executable in the UI; the backend opens a "session" and streams process / file / registry / network events for that target. The native capture layer (ETW, minifilter, registry hooks) is intentionally a stub today — most of what's wired up is the session lifecycle, transport, and UI shell that the real capture service will plug into.

## Components

Three top-level directories, each owns one tier:

- `backend/` — FastAPI app (Python 3.10+ syntax: PEP 604 unions, `from __future__ import annotations`). Single module: `backend/app/main.py`. Pinned deps in `backend/requirements.txt`: fastapi 0.115.6, uvicorn, pydantic 2.10.5, **psutil 7.2.2** (process listing + descendant enumeration), **pywintrace 0.2.0** (ETW). `main.py` injects the repo root into `sys.path` so it can `from service.capture_service import …`.
- `ui/` — React 18 + TypeScript + Vite 6 single-page app. Tailwind is loaded via the `cdn.tailwindcss.com` `<script>` in `ui/index.html` (no PostCSS / Tailwind config in the repo) — utility classes work at runtime but won't be tree-shaken or type-checked.
- `service/` — Windows capture layer. `service/capture_service.py` is the real ETW pipeline (no longer a stub). It is a regular Python package (`service/__init__.py`) imported by the backend; do not move it.

The empty `backend/app/capture/`, `backend/app/utils/`, and `backend/app/static/` directories are reserved scaffolding — fine to populate, don't delete them assuming they're stale.

## Architecture

`backend/app/main.py` wires four collaborators:

- `SessionStore` — dict of sessions, a `defaultdict(deque(maxlen=50_000))` ring buffer of `ActivityEvent`s per session, and a `session_id -> CaptureService` map. No more seeded sample events; sessions stay empty until ETW emits.
- `EventHub` — async fan-out. Each WebSocket subscriber gets its own `asyncio.Queue(maxsize=4096)`; `publish()` uses `put_nowait` and silently drops + unsubscribes any queue that fills up (slow consumers get disconnected, not blocked). Queue size was bumped from 256 to handle ETW burst rates.
- `CaptureService` (`service/capture_service.py`) — owns one ETW user-mode session per tracked process. Subscribes to four manifest providers: Microsoft-Windows-Kernel-File / -Registry / -Process / -Network. The ETW callback runs on a pywintrace consumer thread — `_make_event_callback()` in `main.py` hands events back to the asyncio loop via `asyncio.run_coroutine_threadsafe`. The descendant PID set is pre-seeded from `psutil.Process.children(recursive=True)` and grown live from kernel ProcessStart events whose `ParentProcessID` is already tracked. A `FileObject -> path` cache (populated on Create, cleared on Close) lets Read/Write events resolve to filenames since those events only carry the FileObject pointer. NT device paths (`\Device\HarddiskVolumeN\...`) are translated to DOS letters via `QueryDosDeviceW`.
- FastAPI app — REST for session CRUD + event ingest (`POST /api/sessions/{id}/emit`), `GET /api/processes` (psutil snapshot for the UI picker), `DELETE /api/sessions/{id}` to stop capture, WebSocket at `/ws/sessions/{id}` that first replays the buffered history then tails new events.

State is in-memory only: restarting the backend wipes sessions, events, and stops every ETW session. There is no auth, and CORS is wide open (`allow_origins=["*"]`) — both are fine for the local-only scaffold but need to change before this is exposed.

### Admin requirement

Kernel ETW providers cannot be enabled from a limited token. `is_admin()` is checked in `POST /api/sessions`; without elevation, the session is created with `capture: "needs_admin"` and no events stream — the UI shows an amber banner. Use `run-elevated.ps1` at the repo root to relaunch the backend with UAC elevation, or start uvicorn from an Administrator shell.

### UI ↔ backend coupling

The UI assumes it is served from the same origin as the API. `ui/src/main.tsx` calls relative paths (`/api/...`) and constructs the WebSocket URL by swapping the scheme on `window.location.origin`. Two ways to run it:

1. **Dev**: `cd ui && npm run dev` (Vite on :5173) plus uvicorn on :8000 — but the UI's relative fetches will hit :5173 and fail. Use a Vite proxy or run the built UI through the backend.
2. **Built**: `cd ui && npm run build` produces `ui/dist/`. The backend computes `STATIC_DIR = BASE_DIR / "ui" / "dist"` (where `BASE_DIR` is `Path(__file__).resolve().parents[2]`, i.e. the repo root) and mounts `ui/dist/assets` at `/assets`, with `GET /` returning `ui/dist/index.html`. If `ui/dist` doesn't exist the backend still runs but `/` returns 404 ("ui not built"). Moving `main.py` will break the `parents[2]` calculation.

## Commands

Backend (run from `backend/`):
```
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # non-admin: sessions get capture:"needs_admin"
```

For real ETW capture, launch elevated. From the repo root:
```
powershell -ExecutionPolicy Bypass -File run-elevated.ps1
```
The script self-elevates via UAC and runs uvicorn on :8000.

UI (run from `ui/`):
```
npm install
npm run build      # writes ui/dist/ — required for the backend's "/" route
npm run dev        # standalone dev server (won't see /api unless proxied)
```

There is no test suite, linter, or formatter configured in this repo yet.

# Architecture

## Component diagram

```
                       ┌──────────────────────────────┐
                       │  target.exe (any process)    │
                       │  + descendants               │
                       └──────────────┬───────────────┘
                                      │  ETW kernel events
                                      │  (4 manifest providers)
                                      ▼
                  ┌─────────────────────────────────────────┐
                  │  tracker_capture.exe   (C++17, ~600 LOC)│
                  │   ├─ EtwSession        StartTraceW etc. │
                  │   ├─ EventConsumer     OpenTrace +       │
                  │   │                    ProcessTrace      │
                  │   ├─ TdhParser         TdhGetEventInfo   │
                  │   ├─ PathTranslator    QueryDosDeviceW   │
                  │   ├─ PidFilter         + descendants     │
                  │   └─ ListProcesses     Toolhelp32        │
                  └────────────────┬────────────────────────┘
                                   │  NDJSON
                                   │   1) {"type":"hello","version":"1.0",...}
                                   │   2) event lines (any order)
                                   │   3) {"type":"stats",...} every 1s
                                   ▼
                  ┌─────────────────────────────────────────┐
                  │  service/capture_service.py             │
                  │   thin subprocess wrapper                │
                  │   - hello-sentinel handshake             │
                  │   - stdout pump → on_event(payload)      │
                  │   - stderr pump → activity_tracker.native│
                  │   - stop() ladder (close stdin → wait    │
                  │     → terminate → kill)                  │
                  └────────────────┬────────────────────────┘
                                   │  on_event(dict)
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │  backend/app/   (FastAPI)                             │
        │  ┌──────────────┐   ┌──────────────────────────────┐ │
        │  │ EventHub     │──▶│ SessionStore                 │ │
        │  │ asyncio      │   │  ├─ ring buffer  deque(50k)  │ │
        │  │ subscribers  │   │  ├─ writer thread (batched)  │ │
        │  └──────┬───────┘   │  ├─ retention sweep (30d)    │ │
        │         │           │  └─ SQLite WAL (events.db)   │ │
        │         │           └──────────────────────────────┘ │
        │         │                                              │
        │         │           ┌──────────────────────────────┐ │
        │         │           │ Observability                │ │
        │         │           │  ├─ JSON formatter           │ │
        │         │           │  ├─ trace-id contextvar      │ │
        │         │           │  ├─ 5 log streams (Rotating) │ │
        │         │           │  ├─ Prometheus /metrics      │ │
        │         │           │  └─ /api/health (enriched)   │ │
        │         │           └──────────────────────────────┘ │
        │         │                                              │
        │         │           ┌──────────────────────────────┐ │
        │         │           │ Icons (ctypes)               │ │
        │         │           │  SHGetFileInfoW + GDI → PNG  │ │
        │         │           │  SHA1 disk cache             │ │
        │         │           └──────────────────────────────┘ │
        └─────────┼──────────────────────────────────────────────┘
                  │
        ┌─────────┴────────┐                          ┌──────────────┐
        │  WebSocket       │                          │  REST        │
        │  /ws/sessions/   │                          │  /api/*      │
        │  /ws/logs/       │                          │  /metrics    │
        └─────┬────────────┘                          └──────┬───────┘
              │                                              │
              ▼                                              ▼
        ┌────────────────────┐                  ┌────────────────────┐
        │  React UI          │                  │  MCP server         │
        │  (Vite + Tailwind) │                  │  (stdio FastMCP)    │
        │   ├─ EventTable    │                  │  14 tools          │
        │   ├─ LogsTab       │                  │   6 resources      │
        │   ├─ ProcessPicker │                  │   4 prompts        │
        │   └─ Drawer        │                  └──────┬─────────────┘
        └────────────────────┘                          │
                                                        ▼
                                                  MCP client
                                                  (any compatible host)
```

## Concurrency model

| Thread | Purpose | Notes |
|---|---|---|
| Main thread (Python) | uvicorn / asyncio loop | Event ingestion + WS broadcast happen here. |
| Native consumer thread (in `tracker_capture.exe`) | `ProcessTrace()` blocks; emits events via stdout. | Stops when `ControlTraceW(EVENT_TRACE_CONTROL_STOP)` fires. |
| Native stats thread (in `tracker_capture.exe`) | Emits `{"type":"stats"}` line every 1 s. | `cv.wait_for` so shutdown is prompt. |
| Native stdin watcher (in `tracker_capture.exe`) | Reads stdin; EOF triggers clean shutdown. | Lets the parent kill us by closing the pipe. |
| Python stdout pump | Reads NDJSON from native; calls `on_event`. | Daemon thread. |
| Python stderr pump | Reads stderr; routes to `activity_tracker.native` logger. | Daemon thread. |
| SQLite writer thread (Python) | Owns its own SQLite connection; batches inserts. | Independent of FastAPI request threads. Reader requests share a separate locked connection. |
| FastAPI request threads | Serve REST + WS. | Read events via `store.query_events` (its own connection per call). |

## Persistence schema

`backend/app/db/schema.sql`:

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    exe_path TEXT NOT NULL,
    pid INTEGER NOT NULL,
    pid_create_time REAL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    capture TEXT NOT NULL,
    capture_error TEXT
);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    pid INTEGER, ppid INTEGER,
    path TEXT, target TEXT, operation TEXT,
    details_json TEXT
);

CREATE INDEX idx_events_session_ts   ON events (session_id, ts);
CREATE INDEX idx_events_session_kind ON events (session_id, kind);
CREATE INDEX idx_events_session_pid  ON events (session_id, pid);
```

PRAGMAs at startup: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`.

## Why a ring buffer in front of SQLite

The asyncio `EventHub` broadcasts the live event to WebSocket subscribers from the in-memory ring (`deque(maxlen=50_000)`) — instant, no disk hit. The writer thread persists the same event asynchronously to SQLite in batches. Reading historical events (`query_events`, `iter_events`, export) goes to SQLite. Live tail uses the ring; restart-survival uses SQLite. This split lets us absorb 1000+ events/sec spikes without blocking either the live broadcast or the writer.

## Path translation

Native `path_translator.cpp::BuildDosDeviceMap()` calls `QueryDosDeviceW` for every drive letter A–Z at startup and stores the resulting NT-prefix → DOS-letter pairs sorted longest-first. UNC paths handle `\Device\Mup\…` and `\Device\LanmanRedirector\…`. New volumes mounted after startup are picked up only on the next capture-session start. Nothing is hardcoded.

## Security boundary: localhost + CORS allowlist

Single-user, not redistributed. Localhost-bind plus a tight CORS allowlist for `127.0.0.1` / `localhost` is sufficient. There is intentionally no auth — adding a token would create a shared-secret with no benefit for a single-user local tool. If LAN exposure ever becomes a requirement, see `docs/threat-model.md` for the upgrade path (token middleware skeleton already in place via `MCP_TRACKER_TOKEN`).

## Why native C++ for ETW and not Python

`pywintrace` 0.2.0 (last release 2019) was the original Python ETW path. It was unmaintained, GIL-bound, and limited in keyword expressiveness. Phase 9 replaced it with a native C++17 binary that subscribes directly via Windows ETW APIs (`StartTraceW` / `EnableTraceEx2` / `OpenTraceW` / `ProcessTrace` / TDH). The Python wrapper became a thin subprocess pump (~370 LOC). All path translation, FileObject caching, and PID filtering moved into C++. The hello-sentinel + heartbeat NDJSON protocol catches wire-format drift between the two layers.

## MCP integration

`mcp/` is a separate Python package that talks to the FastAPI HTTP surface only — never imports the tracker's modules. This decouples lifecycles (the tracker runs admin; the MCP bridge doesn't need to) and matches the standard MCP integration pattern. 14 tools, 6 resources, 4 prompt templates via `mcp.server.fastmcp.FastMCP` over stdio. See `mcp/README.md`.

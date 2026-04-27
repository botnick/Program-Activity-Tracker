# Architecture

## Component diagram

```
                                       (Windows kernel)
                                              |
                                       ETW kernel providers
                                              |
                                              v
+---------------------------+        +--------------------------+
| service/capture_service.py|<-------|  pywintrace consumer     |
|  CaptureService (thread)  |        |  thread (per session)    |
+-----------+---------------+        +--------------------------+
            |
            | callback(payload: dict)            (sync, on capture thread)
            |  - store.add_event()    ---> SessionStore ring + writer queue
            |  - asyncio.run_coroutine_threadsafe(hub.publish(...))
            v
+---------------------------+        +--------------------------+
| backend.app.store         |        |  EventHub                |
|  SessionStore             |  +-----|  asyncio.Queue per WS    |
|   - in-memory ring buffer |  |     +--------------------------+
|   - writer thread + queue |  |             ^
|   - SQLite (WAL)          |  |             | put_nowait
|     events.db             |  |             | (drops slow consumers)
+-----------+---------------+  |     +--------------------------+
            |                  +-----|  WebSocket /ws/sessions/ |
            |                        |  (FastAPI)               |
            v                        +--------------------------+
+---------------------------+
| backend.app.api_routes    |  HTTP  +--------------------------+
|  REST + WebSocket router  |<-------|  React UI (ui/dist)      |
+---------------------------+        +--------------------------+
            ^
            | HTTP
            |
+---------------------------+
| mcp/ (Phase 4)            |  - read-only client of the REST API
+---------------------------+
```

## Concurrency model

Three logical execution contexts cooperate inside the backend process:

| Context             | Owner                                     | What it does                                                                    |
|---------------------|-------------------------------------------|---------------------------------------------------------------------------------|
| Asyncio loop        | uvicorn / FastAPI                         | HTTP, WebSocket fan-out, lifespan hooks                                         |
| Capture thread(s)   | `CaptureService.start()` (per session)    | pywintrace consumer + per-event callback that hands off to the store and hub   |
| Storage writer      | `SessionStore._writer_thread` (1 total)   | Drains a `queue.Queue` and batches `INSERT`s into `events.db`                   |

The write hot path is intentionally **non-blocking**:

1. Capture thread calls `store.add_event(event)`.
2. `add_event` appends to the in-memory `deque` (live tail) and `put`s on
   `_write_q`. Neither operation blocks on disk.
3. Capture thread schedules `hub.publish(...)` via
   `asyncio.run_coroutine_threadsafe` so the fan-out runs on the asyncio
   loop's thread.
4. The writer thread wakes up, batches up to `_WRITER_BATCH_MAX` (1000)
   events or `_WRITER_BATCH_INTERVAL` (100 ms) of arrivals, then commits
   them in a single transaction on its own SQLite connection.

WebSocket subscribers each have a private `asyncio.Queue(maxsize=…)`.
`EventHub.publish` uses `put_nowait`; if a queue fills, the subscriber is
silently dropped from the set rather than back-pressuring the producer.
This is the explicit contract: **slow consumers get disconnected, never
slow down capture**.

## Persistence schema

`backend/app/db/schema.sql` (applied idempotently by
`backend.app.db.migrations.apply_migrations`):

```sql
CREATE TABLE sessions (
    session_id      TEXT PRIMARY KEY,
    exe_path        TEXT NOT NULL,
    pid             INTEGER NOT NULL,
    pid_create_time REAL,
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL,
    capture         TEXT NOT NULL,
    capture_error   TEXT
);

CREATE TABLE events (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    ts           TEXT NOT NULL,        -- ISO-8601 UTC
    kind         TEXT NOT NULL,        -- "process" | "file" | "registry" | "network" | ...
    pid          INTEGER,
    ppid         INTEGER,
    path         TEXT,
    target       TEXT,
    operation    TEXT,
    details_json TEXT                  -- stringified JSON; nullable
);

CREATE INDEX idx_events_session_ts   ON events (session_id, ts);
CREATE INDEX idx_events_session_kind ON events (session_id, kind);
CREATE INDEX idx_events_session_pid  ON events (session_id, pid);
```

The DB is opened in WAL mode by `apply_migrations`. Writes go through a
dedicated connection on the writer thread; reads go through a shared
`check_same_thread=False` connection guarded by `RLock`. Streaming
exports (`iter_events`) open a private throw-away connection so the
generator can outlive a single request.

## Why a ring buffer in front of SQLite?

Two reasons:

1. **Live tail without disk I/O on the request path.** The WebSocket
   "replay history then stream" sequence can serve hundreds of recent
   events without reading from SQLite. Disk reads only happen for the
   filtered/exported queries.
2. **Backpressure isolation.** If the writer thread falls behind (slow
   disk, big batch, fsync stall), the producer keeps appending to the
   deque. Bounded memory growth is preferred over event loss; the deque
   has a hard cap (`TRACKER_EVENT_RING_SIZE`, default 50 000), so once
   full it drops oldest-first — but the *durable* SQLite path keeps
   accepting writes.

## Security boundary: localhost-only + CORS allowlist

The default bind is `127.0.0.1:8000`. CORS is locked to
`http://127.0.0.1:8000`, `http://localhost:8000`, and the Vite dev
servers on `:5173` (configurable via `TRACKER_CORS_ORIGINS`).

There is **no auth.** Anyone with a shell on the host can hit the API.
We accept this because:

- The capture data describes activity on this machine and is already
  visible to any local Administrator.
- The tool is intended for a single operator on their own workstation.
- Adding auth without a key-management story leaves a worse footgun
  (hard-coded shared secret in env file).

If exposing the API beyond localhost is ever required, **don't.** Put
the backend behind a reverse proxy that does TLS + token auth + IP ACLs
(see `docs/threat-model.md` for the hardening checklist).

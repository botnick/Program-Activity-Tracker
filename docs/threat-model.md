# Threat Model

## Scope

The Activity Tracker is a **single-user, single-host, localhost-only**
introspection tool. It elevates to Administrator to subscribe to ETW
kernel providers, then exposes a small REST + WebSocket API to a UI
running in the same browser/host. This document records the trust
boundaries we depend on and the failure modes if they're crossed.

## Trust boundaries

```
+---------------------------------------------------------------+
|  Host machine (single-user trust domain)                      |
|                                                               |
|  +----------------+   ETW (kernel)   +----------------------+ |
|  | Windows kernel | ---------------> | CaptureService       | |
|  +----------------+                   |  (Administrator)    | |
|                                       +----------+-----------+ |
|                                                  |            |
|                                                  v            |
|                                       +-----------------------+|
|                                       | FastAPI on 127.0.0.1  ||
|                                       | (no authentication)   ||
|                                       +----------+-----------+|
|                                                  ^            |
|                                                  | localhost  |
|                                                  |            |
|                                       +-----------------------+|
|                                       | Browser / MCP client  ||
|                                       +-----------------------+|
+---------------------------------------------------------------+
                          |
                       (no traffic
                       crosses this
                        boundary)
                          v
                +---------------------+
                | LAN / Internet      |
                +---------------------+
```

Inside the host, anything running as the operator is trusted at the
same level as the API. Outside the host, **no traffic is intended to
cross**; the bind is `127.0.0.1` and the firewall should not have a
hole for port 8000.

## Data sensitivity

ETW emits process arguments, file paths, registry keys, and network
endpoints. None of that is privileged beyond what kernel ETW already
captures, but the *aggregated history* in `events.db` is sensitive in a
way no individual record is:

- File paths often leak credentials in URLs, project names, customer
  identifiers, and personal data (`C:\Users\<name>\Documents\…`).
- Registry hits expose installed software, license keys, and per-user
  tokens.
- Process command lines occasionally contain secrets passed via flags
  (badly written installers, CI helpers).

**Operational rule:** treat `events.db`, `logs/tracker.log`, and any
exported `.jsonl`/`.csv` like a sysmon archive. Never share without
redaction. The `GET /api/sessions/{id}/export` endpoint exists partly
so a redaction step can sit between the raw DB and any handoff.

## Attacker model: local user

The backend has **no authentication**. Any local process on the host
can hit `127.0.0.1:8000` and:

- List processes (`GET /api/processes`).
- Start a capture session against any PID the running backend can see
  (i.e. anything if the backend is Administrator).
- Read all historical events via `/api/sessions/{id}/events` and
  `/export`.
- Subscribe to the live WebSocket stream.

This is **by design** — it's a single-user local tool. If you need to
defend against other local users on a multi-tenant box, do not run this
backend.

## Attacker model: remote / LAN

If the backend is exposed off-host, the unauthenticated API becomes a
remote-event-feed and remote-process-listing oracle. Don't expose it.
If you must, the minimum hardening is:

1. **Bind to localhost only**, then forward through a reverse proxy
   (nginx, Caddy) that handles TLS + auth.
2. **Require a bearer token** at the proxy. Generate it once, hand it
   to operators out-of-band, rotate manually.
3. **IP allowlist** at the proxy or via Windows Firewall.
4. **Origin pinning**: tighten `TRACKER_CORS_ORIGINS` to the exact host
   the UI is served from. Drop the `localhost`/`127.0.0.1` defaults.
5. **Audit log**: enable proxy access logs and forward them to an
   immutable store.

None of the above is implemented in this repo today; if a future phase
needs it, follow the list above rather than bolting auth into FastAPI
directly.

## ETW provider GUIDs and "extra surface"

The kernel providers we subscribe to (Process, FileIO, Registry,
TcpIp, Image) are public well-known GUIDs. The data we receive is the
same data Sysmon, ProcMon, ETL traces, and any kernel-mode tracer can
see. We do not hook the kernel, install drivers, or escalate beyond
what `Microsoft-Windows-Kernel-*` already exposes. The Administrator
requirement is purely so that `EnableTraceEx2` succeeds.

## Defenses we rely on

- **Windows ACLs** on `events.db` and `logs/`. The default LocalSystem
  install writes them with admin-only ACLs; preserve that if you change
  the install path.
- **WAL files** (`events.db-wal`, `events.db-shm`) inherit the same
  ACLs; they must be backed up alongside the main DB.
- **`is_safe_exe_path`** in `backend.app.observability` rejects
  non-absolute / `..` / non-Windows-drive paths from the
  `exe_path` request field, so an attacker can't make us spawn capture
  against `\\evilshare\foo.exe` or `/etc/passwd`.
- **Pinned dependencies** in `pyproject.toml` (FastAPI, uvicorn,
  pydantic, psutil, pywintrace, prometheus-client) reduce drive-by
  upgrades. Dependabot opens grouped weekly PRs; review them before
  merging.

## Known footguns

- Restarting the backend without `flush()` could lose up to
  `_WRITER_BATCH_INTERVAL` (100 ms) worth of buffered events. The
  shutdown hook calls `store.shutdown()` to drain.
- `seed()` in `SessionStore.create()` is gone now, but if it were
  ever reintroduced, sample events would mix with real captures.
- Running the dev UI (`vite` on `:5173`) hits a different origin than
  the backend. The CORS allowlist permits this, but it means the
  cross-origin browser policy is your only barrier — keep the dev
  server bound to localhost.

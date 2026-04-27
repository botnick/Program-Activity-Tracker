# Operations Guide

This guide covers running the Activity Tracker backend in long-lived /
unattended deployments. The application is intended for **single-host,
single-operator** use; treat it like a developer tool, not a network
service.

## Running as a Windows Service (NSSM)

ETW kernel providers require Administrator. The simplest unattended path is
[NSSM](https://nssm.cc/) wrapping uvicorn under the LocalSystem account (or
a service account with the `SeSecurityPrivilege` right):

```powershell
# 1. Install (one-shot, opens NSSM's GUI)
nssm install ActivityTracker "C:\Path\To\python.exe" `
    "-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
nssm set ActivityTracker AppDirectory "C:\Users\btx\Desktop\kuy"
nssm set ActivityTracker AppStdout    "C:\Users\btx\Desktop\kuy\logs\stdout.log"
nssm set ActivityTracker AppStderr    "C:\Users\btx\Desktop\kuy\logs\stderr.log"
nssm set ActivityTracker AppRotateFiles 1
nssm set ActivityTracker AppRotateBytes 104857600
nssm set ActivityTracker ObjectName LocalSystem
nssm set ActivityTracker Start SERVICE_AUTO_START

# 2. Start
nssm start ActivityTracker

# 3. Status / logs
nssm status ActivityTracker
Get-Content -Tail 200 -Wait C:\Users\btx\Desktop\kuy\logs\tracker.log
```

Notes:
- LocalSystem already has Administrator privileges. If you prefer a
  dedicated account, give it the `SeDebugPrivilege` and
  `SeSecurityPrivilege` rights and add it to the
  `Performance Log Users` group.
- NSSM auto-restarts on crash by default. Adjust the throttle / exit-action
  policy if uvicorn ever spirals.

## Logs

`backend/app/observability.configure_logging()` wires two handlers on the
root logger:

| Handler  | Format            | Destination                                |
|----------|-------------------|--------------------------------------------|
| Console  | human-readable    | stdout (captured by NSSM)                  |
| File     | one JSON per line | `<repo>/logs/tracker.log` (rotating)       |

The file handler uses `RotatingFileHandler(maxBytes=100MB, backupCount=5)`,
i.e. up to **500 MB** total before old rolls are dropped. Rotation is
size-triggered, not time-triggered. Override the directory with
`TRACKER_LOG_DIR` and the level with `TRACKER_LOG_LEVEL` (`DEBUG`,
`INFO`, `WARNING`, `ERROR`).

Each JSON record carries: `ts`, `level`, `logger`, `message`, optional
`trace_id`, plus any keyword extras a caller attached via
`logger.info(..., extra={...})`. Request access logs include
`method`, `path`, `status_code`, `duration_ms`.

## Metrics (Prometheus)

`GET /metrics` returns the Prometheus exposition format when
`prometheus-client` is installed and `TRACKER_METRICS_ENABLED=true`
(the default). Useful series:

| Metric                                  | Type      | Labels  | Meaning                                |
|-----------------------------------------|-----------|---------|----------------------------------------|
| `tracker_events_total`                  | counter   | `kind`  | ETW events ingested                    |
| `tracker_events_dropped_total`          | counter   | -       | Events dropped by slow subscribers     |
| `tracker_capture_errors_total`          | counter   | -       | Errors raised inside capture pipeline  |
| `tracker_capture_sessions_live`         | gauge     | -       | Sessions with an attached CaptureService |
| `tracker_subscribers`                   | gauge     | -       | Live WebSocket subscribers             |
| `tracker_file_object_cache_size`        | gauge     | -       | FileObject -> path LRU size            |
| `tracker_tracked_pids_total`            | gauge     | -       | Distinct tracked PIDs across captures  |
| `tracker_request_duration_seconds`      | histogram | `path`  | HTTP request latency                   |

Sample alert rules:

```yaml
groups:
  - name: activity-tracker
    rules:
      - alert: TrackerEventLossSpike
        expr: rate(tracker_events_dropped_total[5m]) > 0
        for: 5m
        annotations:
          summary: "Tracker dropping events (slow WS subscriber)"

      - alert: TrackerCaptureErrors
        expr: rate(tracker_capture_errors_total[5m]) > 0.1
        for: 10m

      - alert: TrackerHighFileCache
        expr: tracker_file_object_cache_size > 200000
        for: 30m
        annotations:
          summary: "FileObject cache larger than expected; possible leak"
```

## Troubleshooting

### Every session reports `capture: needs_admin`
The backend is not running as Administrator. ETW kernel providers cannot
be started from a standard token. Re-launch via `run-elevated.ps1` or
re-install the NSSM service under LocalSystem.

### Empty event stream after creating a session
1. Check `tracker_events_total` — if it's not incrementing, the capture
   thread isn't producing.
2. Confirm the target PID still exists (`Get-Process -Id <pid>`); the
   tracker doesn't follow short-lived children unless they fork from the
   target.
3. Look at `tracker.log` for `capture_errors` records.

### Memory growth
The most likely cause is an unbounded FileObject cache. Watch
`tracker_file_object_cache_size`; the default cap is
`TRACKER_FILE_OBJECT_CACHE_SIZE=100000` and entries should evict via LRU
once full. Restart the backend if the gauge keeps climbing — it indicates
a regression in the capture layer.

### `events.db` growing without bound
There is **no automatic GC** for events at this stage. The DB lives at
`<repo>/events.db` (overridable via `TRACKER_DB_PATH`). To reclaim space:

```powershell
# Stop the service first.
nssm stop ActivityTracker

# Truncate (drop everything; sessions metadata kept):
sqlite3 events.db "DELETE FROM events; VACUUM;"

# Or delete one session's events:
sqlite3 events.db "DELETE FROM events WHERE session_id='<uuid>'; VACUUM;"

nssm start ActivityTracker
```

Prefer `GET /api/sessions/{id}/export` to back up data before truncating.

## Backup / Data Export

`GET /api/sessions/{session_id}/export?format=jsonl` (or `format=csv`)
streams the full event history for a session. It supports the same
filters as `GET /api/sessions/{id}/events` (`kind`, `since`, `until`,
`q`). Use it for offline analysis, archival, and as a redacted handoff
format.

Whole-DB backups: copy `events.db` plus the SQLite sidecars (`-wal`,
`-shm`) while the service is stopped, or use `sqlite3 events.db ".backup
backup.db"` against a running service. **Treat the DB as sensitive** — see
the threat model.

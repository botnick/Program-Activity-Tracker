# Operations

## Daily run

Double-click `start.bat` at the repo root. Stops via `stop.bat` or by closing the CMD window.

## Run as a Windows service (NSSM)

For a long-lived background install, wrap the backend in [NSSM](https://nssm.cc):

```cmd
nssm install ActivityTracker "C:\Path\To\python.exe" "-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
nssm set    ActivityTracker AppDirectory "C:\Path\To\activity-tracker"
nssm set    ActivityTracker AppEnvironmentExtra TRACKER_DB_PATH=C:\ProgramData\ActivityTracker\events.db
nssm set    ActivityTracker AppStdout C:\ProgramData\ActivityTracker\service.out.log
nssm set    ActivityTracker AppStderr C:\ProgramData\ActivityTracker\service.err.log
nssm set    ActivityTracker ObjectName LocalSystem    :: required for ETW
nssm start  ActivityTracker
```

Verify: `Get-Service ActivityTracker` should show `Running`. Logs land in `C:\ProgramData\ActivityTracker\`.

## Logs

Five rotating JSON files in `<repo>/logs/` (or `TRACKER_LOG_DIR`):

| Stream | Source | Cap |
|---|---|---|
| `tracker.log` | root logger (everything) | 100 MB × 5 |
| `events.log` | `activity_tracker.events` | 50 MB × 3 |
| `requests.log` | `activity_tracker.request` (HTTP middleware) | 50 MB × 3 |
| `errors.log` | WARNING+ from any logger | 50 MB × 3 |
| `native.log` | `tracker_capture.exe` stderr | 50 MB × 3 |

Each line is one JSON object: `{ts, level, logger, message, trace_id?, ...extras}`.

Live tail via the UI's **Logs** tab, or:

```cmd
curl http://127.0.0.1:8000/api/logs/native?tail=100
```

WebSocket live stream: `ws://127.0.0.1:8000/ws/logs/native`.

## Metrics (Prometheus)

Scrape `http://127.0.0.1:8000/metrics`. Selected series:

| Metric | Type | Labels |
|---|---|---|
| `tracker_events_total` | counter | `kind` (file/registry/process/network) |
| `tracker_events_dropped_total` | counter | — |
| `tracker_capture_errors_total` | counter | — |
| `tracker_capture_sessions_live` | gauge | — |
| `tracker_subscribers` | gauge | — |
| `tracker_file_object_cache_size` | gauge | `session_name` |
| `tracker_tracked_pids_total` | gauge | — |
| `tracker_request_duration_seconds` | histogram | `path` |

Sample alert (if you ever wire one):

```yaml
- alert: TrackerHighDropRate
  expr: rate(tracker_events_dropped_total[5m]) > 10
  for: 5m
```

## Database maintenance

`events.db` is SQLite WAL mode; defaults to repo root.

- **Retention**: writer thread sweeps events older than `TRACKER_DB_RETENTION_DAYS` (default 30) every `TRACKER_DB_RETENTION_CHECK_MINUTES` (default 60). Set days to `0` to disable.
- **Vacuum**: not automatic. To reclaim disk after large deletions:
  ```cmd
  python -c "import sqlite3; sqlite3.connect('events.db').execute('VACUUM').close()"
  ```
- **Inspect**:
  ```cmd
  sqlite3 events.db ".schema"
  sqlite3 events.db "SELECT kind, COUNT(*) FROM events GROUP BY kind"
  ```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Sessions all show `capture: needs_admin` | Backend not running elevated | Use `start.bat` (auto-elevates) or `run-elevated.ps1` |
| `RuntimeError: Native binary not found` | `tracker_capture.exe` missing | `start.bat` builds it; if VS Build Tools missing, install VS 2022/2026 with C++ workload |
| No events stream | Target process exited; or kernel ETW session collided | Check `tracker_events_total` metric; restart session |
| `database is locked` errors | Multiple writer connections | Should not happen — writer owns its own conn; report as bug |
| `events.db` GBs large | Retention disabled or off | Set `TRACKER_DB_RETENTION_DAYS=7` and restart |
| Defender quarantines `tracker_capture.exe` | Heuristic match | Run `scripts\setup-defender-exclusion.ps1` once |
| Port 8000 in use | Stale instance | `stop.bat` or kill PID via `netstat -ano \| findstr :8000` |

## Backup / data export

Per-session export from the UI ("Export CSV" / "Export JSONL" buttons) or:

```cmd
curl "http://127.0.0.1:8000/api/sessions/<id>/export?format=jsonl" -o session.jsonl
```

Whole-DB backup: copy `events.db` + `events.db-wal` + `events.db-shm` while the backend is stopped (or use `sqlite3` `.backup` for online).

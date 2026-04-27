# Threat Model

## Scope

Single-user, local-only Windows tool. The threat model assumes:

- The user owns and trusts the machine they're running on.
- The tracker is **not redistributed**; binaries don't leave the user's box.
- The tracker is **not exposed to LAN** — bind is `127.0.0.1` only.

If any of those change, see "If you ever expose this" at the bottom.

## Trust boundaries

```
   ┌─────────────────┐         ┌──────────────────────────┐
   │  user (admin)   │ ──UAC──▶│  tracker_capture.exe     │
   │  on the local   │         │  (kernel ETW consumer)   │
   │  machine        │         └──────────┬───────────────┘
   └─────────────────┘                    │ subprocess pipe
                                          ▼
                                  ┌──────────────────┐
                                  │  FastAPI backend │
                                  │  (admin too)     │
                                  └────────┬─────────┘
                                           │ HTTP / WS (loopback)
                                           ▼
                                  ┌──────────────────┐
                                  │ browser, MCP CLI │
                                  └──────────────────┘
```

Everything inside the trust boundary is the same admin-elevated user.
There is **no privilege boundary** between the UI and the backend — the user
calling the API already has the admin token that started the backend.

## What the design defends against

| Threat | Defense |
|---|---|
| Target process inspection / tampering | None needed — we never inject, never hook, never modify the target. |
| Path-traversal via `exe_path` query | `is_safe_exe_path` rejects `..`, non-absolute, UNC-without-drive. |
| WebSocket overflow disconnects unnoticed | `EventHub.dropped_subscribers` counter + warning log. |
| Slow consumer back-pressuring capture | Per-subscriber bounded queue; drop subscriber, never block publisher. |
| PID reuse leaking events to wrong session | `pid_create_time` verified each event. |
| ETW session orphaned after crash | Native `EtwSession::SweepOrphans()` at startup. |
| Native binary deadlock | Python `stop()` ladder times out and falls through to `terminate` / `kill`. |
| Native binary version drift | `{"type":"hello","version":"1.0"}` handshake on first stdout line. |
| AV/EDR quarantining `tracker_capture.exe` | Optional `scripts/setup-defender-exclusion.ps1`. |
| `events.db` growing unbounded | 30-day retention sweep in writer thread. |
| Log files growing unbounded | RotatingFileHandler caps each stream. |
| MCP server polluting forensic timelines | `emit_event` tool gated behind `MCP_TRACKER_ALLOW_EMIT=1` (default off). |
| MCP stdio framing corruption | All tracker logs go to stderr; HTTP-only client coupling. |
| Non-Latin filenames mojibake | TDH parser tries `CP_UTF8` strict, falls back to `CP_ACP`. |

## What the design does NOT defend against (acceptable)

- A malicious local admin user. They already have the keys to the kingdom.
- A second process running as the same admin user querying `/api/sessions`. There is no auth — by design for the single-user case. If you ever want to lock it down, plumb the `MCP_TRACKER_TOKEN` skeleton end-to-end.
- Sensitive paths in events. ETW captures whatever the kernel sees. If the target reads `C:\Users\<you>\Documents\secret.txt` we record the path. Treat `events.db` and the `logs/` folder as confidential.
- A nation-state planting drivers below ETW. Out of scope.

## Data sensitivity

The `events.db` file and `logs/native.log` may contain:

- Full file paths (potentially in user's home, including secret-shaped names like `wallet.json`).
- Registry key/value names.
- Network endpoints the target connects to.
- Process command lines (where the kernel exposes them).

Don't share these files casually. Personal use only.

## If you ever expose this

If you decide to bind beyond `127.0.0.1` (LAN, VPN, SSH-tunneled to a server):

1. Set `TRACKER_TOKEN=<random>` env var (the env-reading code path is plumbed but currently no middleware enforces it — wire one up).
2. Tighten `TRACKER_CORS_ORIGINS` to the specific origin you serve the UI from.
3. Put it behind TLS (a reverse proxy like Caddy with auto-cert is the easiest path).
4. Consider per-user file ACLs on `events.db`.
5. Audit `tests/test_observability.py::test_is_safe_exe_path` — make sure the path validator still rejects everything you care about.

These are not done by default because they add cognitive load with zero benefit for the documented single-user use case.

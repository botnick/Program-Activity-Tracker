"""Sweep stale ETW sessions left behind by crashed prior runs.

When a process holding an ETW session terminates without calling
``ControlTraceW(STOP)``, the kernel keeps the session active until reboot
or an explicit ``logman stop``. ``CaptureService.start()`` reuses a
deterministic session-name prefix (``ActivityTracker-``); on every start
we sweep any leftover sessions that match so the new session can be
created without ``ERROR_ALREADY_EXISTS``.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def _list_sessions(prefix: str) -> list[str]:
    """Return active ETW sessions whose names start with ``prefix``."""
    try:
        completed = subprocess.run(
            ["logman", "query", "-ets"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        logger.warning("logman not found on PATH; skipping ETW orphan sweep")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("logman query -ets timed out; skipping ETW orphan sweep")
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("logman query -ets failed: %s", exc)
        return []

    output = completed.stdout or ""
    matches: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip header / separator lines.
        lowered = line.lower()
        if lowered.startswith("data collector set") or lowered.startswith("name"):
            continue
        if set(line) <= {"-", " "}:
            continue
        first = line.split()[0]
        if first.startswith(prefix):
            matches.append(first)
    return matches


def sweep_orphan_sessions(prefix: str = "ActivityTracker-") -> list[str]:
    """Stop every active ETW session whose name starts with ``prefix``.

    Returns the list of session names that were successfully stopped. The
    function never raises: any failure (logman missing, timeout, non-zero
    exit) is logged at WARNING and treated as "nothing stopped".
    """
    stopped: list[str] = []
    sessions = _list_sessions(prefix)
    for name in sessions:
        try:
            result = subprocess.run(
                ["logman", "stop", name, "-ets"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            logger.warning("logman not found on PATH; cannot stop %s", name)
            return stopped
        except subprocess.TimeoutExpired:
            logger.warning("logman stop %s timed out", name)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("logman stop %s failed: %s", name, exc)
            continue

        if result.returncode == 0:
            stopped.append(name)
            logger.info("stopped orphan ETW session %s", name)
        else:
            logger.warning(
                "logman stop %s exited %d: %s",
                name,
                result.returncode,
                (result.stderr or result.stdout or "").strip(),
            )
    return stopped

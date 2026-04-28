"""Thin Python orchestrator for the native ETW capture binary.

The native binary in ``service/native/build/`` does all ETW heavy lifting:
session creation, orphan sweep, TDH event parsing, FileObject cache, NT-to-DOS
path translation, descendant PID tracking, IPv4/IPv6 formatting. This module
just spawns the binary, validates a version handshake, and forwards each
JSON event line to the caller's ``on_event`` callback.

Build the binary with::

    cmake -S service/native -B service/native/build -G Ninja -DCMAKE_BUILD_TYPE=Release
    cmake --build service/native/build --config Release

Or use bootstrap.ps1 / start.bat which build it on first run.
"""

from __future__ import annotations

import ctypes
import json
import logging
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

logger = logging.getLogger(__name__)
_native_logger = logging.getLogger("activity_tracker.native")


BASE_DIR = Path(__file__).resolve().parents[1]
BINARY_NAMES = ["tracker_capture.exe"]
BUILD_DIRS = ["service/native/build", "service/native/build/Release"]
SUPPORTED_PROTOCOL_VERSION = "1.0"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


@dataclass
class CaptureTarget:
    exe_path: str
    pid: int
    pid_create_time: float | None = None


def _native_binary_path() -> Path | None:
    candidates = [
        BASE_DIR / "service" / "native" / "build" / "Release" / "tracker_capture.exe",
        BASE_DIR / "service" / "native" / "build" / "tracker_capture.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


class CaptureService:
    """Spawns the native ETW binary and pumps JSON event lines to ``on_event``.

    The binary path is resolved at start(); if missing, start() raises
    RuntimeError with build instructions. The hello sentinel handshake
    catches wire-format drift between Python wrapper and C++ binary.
    """

    BUILD_HINT = (
        "Native binary not found. Build it from a Visual Studio Developer "
        "Prompt with:\n"
        "  cmake -S service/native -B service/native/build -G Ninja -DCMAKE_BUILD_TYPE=Release\n"
        "  cmake --build service/native/build --config Release\n"
        "Or run bootstrap.ps1 / start.bat which builds on first launch."
    )

    def __init__(
        self,
        target: CaptureTarget,
        on_event: Callable[[dict[str, Any]], None],
    ) -> None:
        self.target = target
        self.on_event = on_event
        self._proc: subprocess.Popen[bytes] | None = None
        self._threads: list[threading.Thread] = []
        self._stopped = False
        self._engine = "native"
        # Stats — populated from heartbeat lines.
        self._stats_lock = threading.Lock()
        self._latest_stats: dict[str, Any] = {
            "tracked_pids": 1,           # at least the target pid until first heartbeat
            "file_object_cache_size": 0,
            "key_object_cache_size": 0,
            "errors": 0,
            "last_event_at": None,
        }
        self._dropped_events = 0
        self._session_name: str = (
            f"ActivityTracker-{target.pid}-{uuid.uuid4().hex[:8]}"
        )
        self._session_started_at: str | None = None
        self._error_count = 0   # counts wrapper-side errors (bad JSON from native, etc.)
        self._last_error_log = 0.0
        # Pre-seed descendant pids from psutil so the native binary can include them
        # in the initial filter set (sent via --seed-pids argv).
        self._seed_pids: list[int] = self._collect_seed_pids()

    def _collect_seed_pids(self) -> list[int]:
        try:
            proc = psutil.Process(self.target.pid)
            return [self.target.pid] + [c.pid for c in proc.children(recursive=True)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return [self.target.pid]

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError("CaptureService.stop() already called")
        if not is_admin():
            raise PermissionError(
                "ETW capture requires Administrator. Restart the backend in an elevated shell."
            )
        binary = _native_binary_path()
        if binary is None:
            raise RuntimeError(self.BUILD_HINT)

        self._proc = self._spawn_native(binary)

        # Wait for the hello sentinel (or eof / error).
        try:
            hello = self._wait_for_hello(timeout=10.0)
        except Exception:
            # Whatever happened, reap the process and re-raise.
            try:
                if self._proc is not None:
                    self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            raise

        if hello.get("version") != SUPPORTED_PROTOCOL_VERSION:
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(
                f"native binary protocol version {hello.get('version')!r} "
                f"is not supported (expected {SUPPORTED_PROTOCOL_VERSION!r}). "
                "Rebuild service/native or update the Python wrapper."
            )
        self._session_started_at = hello.get("started_at")
        # If native sent us a different session_name, sync.
        if hello.get("session_name"):
            self._session_name = str(hello["session_name"])

        # Start pumps.
        out_t = threading.Thread(
            target=self._stdout_pump, name="native-capture-stdout", daemon=True
        )
        err_t = threading.Thread(
            target=self._stderr_pump, name="native-capture-stderr", daemon=True
        )
        out_t.start()
        err_t.start()
        self._threads = [out_t, err_t]

        logger.info(
            "ETW capture started [native] (binary=%s, session=%s, target_pid=%d, version=%s)",
            binary, self._session_name, self.target.pid, hello.get("version"),
        )

    def _spawn_native(self, binary: Path) -> subprocess.Popen[bytes]:
        argv = [
            str(binary),
            "--pid", str(self.target.pid),
            "--session-name", self._session_name,
        ]
        if self.target.pid_create_time is not None:
            ms = int(round(float(self.target.pid_create_time) * 1000.0))
            argv.extend(["--pid-create-time", str(ms)])
        # NOTE: The native binary does NOT currently accept --seed-pids; native
        # rebuilds the descendant set from kernel events. We keep the psutil seed
        # in `_seed_pids` only to surface initial coverage in stats() before the
        # first heartbeat arrives.

        try:
            return subprocess.Popen(  # noqa: S603 — argv is fully controlled.
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            raise RuntimeError(f"failed to spawn native capture: {exc}") from exc

    def _wait_for_hello(self, timeout: float = 10.0) -> dict[str, Any]:
        """Read the first stdout line. If the binary fails to start, this
        raises after the process exits or the timeout elapses.
        """
        deadline = time.monotonic() + timeout
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        # readline can block forever — use a small thread to deliver the line
        # OR exploit non-blocking by polling proc.poll().
        line: list[bytes] = []
        line_event = threading.Event()

        def _reader() -> None:
            try:
                ln = proc.stdout.readline()
                line.append(ln)
            finally:
                line_event.set()

        t = threading.Thread(target=_reader, name="native-hello-wait", daemon=True)
        t.start()

        while not line_event.is_set():
            if time.monotonic() > deadline:
                raise RuntimeError("timed out waiting for native hello sentinel")
            if proc.poll() is not None:
                # Process exited before sending hello. Drain stderr for the error.
                try:
                    err = (
                        proc.stderr.read().decode("utf-8", errors="replace")
                        if proc.stderr
                        else ""
                    )
                except Exception:  # noqa: BLE001
                    err = ""
                raise RuntimeError(
                    f"native binary exited (rc={proc.returncode}) before hello sentinel: "
                    f"{err.strip()[:500]}"
                )
            line_event.wait(timeout=0.1)

        raw = line[0] if line else b""
        if not raw:
            # EOF without data — process likely failed.
            raise RuntimeError("native binary closed stdout before sending hello sentinel")
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace").strip())
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"native hello was not valid JSON: {raw!r} ({exc})"
            ) from exc
        if not isinstance(payload, dict) or payload.get("type") != "hello":
            raise RuntimeError(f"native hello did not have type=hello: {payload!r}")
        return payload

    def _stdout_pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except (ValueError, json.JSONDecodeError) as exc:
                    self._error_count += 1
                    now = time.monotonic()
                    if now - self._last_error_log >= 5.0:
                        self._last_error_log = now
                        logger.warning("native: bad JSON line: %s (%s)", line[:200], exc)
                    continue
                if not isinstance(payload, dict):
                    continue
                ptype = payload.get("type")
                if ptype == "stats":
                    with self._stats_lock:
                        for k in (
                            "tracked_pids",
                            "file_object_cache_size",
                            "key_object_cache_size",
                            "errors",
                            "last_event_at",
                        ):
                            if k in payload:
                                self._latest_stats[k] = payload[k]
                    continue
                if ptype == "hello":
                    # Already handled at startup; ignore later occurrences.
                    continue
                # Otherwise treat as an event payload.
                if "timestamp" not in payload and "ts" in payload:
                    payload["timestamp"] = payload["ts"]
                try:
                    self.on_event(payload)
                except Exception as exc:  # noqa: BLE001
                    self._error_count += 1
                    now = time.monotonic()
                    if now - self._last_error_log >= 5.0:
                        self._last_error_log = now
                        logger.warning("native: on_event raised: %s", exc, exc_info=True)
        finally:
            try:
                proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass

    def _stderr_pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                if line.startswith("[info]"):
                    _native_logger.info(line)
                elif line.startswith("[warn]"):
                    _native_logger.warning(line)
                elif line.startswith("[error]"):
                    _native_logger.error(line)
                else:
                    _native_logger.warning(line)
        finally:
            try:
                proc.stderr.close()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:  # noqa: BLE001
                    pass
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            for t in self._threads:
                t.join(timeout=2.0)
            self._proc = None
            logger.info("ETW capture stopped (session=%s)", self._session_name)

    def note_dropped(self, n: int = 1) -> None:
        self._dropped_events += n

    def stats(self) -> dict[str, Any]:
        with self._stats_lock:
            stats = dict(self._latest_stats)
        stats.update({
            "session_name": self._session_name,
            "target_pid": self.target.pid,
            "errors": stats.get("errors", 0) + self._error_count,
            "dropped": self._dropped_events,
            "engine": self._engine,
        })
        return stats

"""Real-binary smoke test: spawn ``tracker_capture.exe`` against the test
process itself, generate a little file activity, and assert at least one
event line shows up on stdout within a few seconds.

Gated behind both ``is_admin()`` and binary-present checks — skipped on
unprivileged dev / CI runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from service.capture_service import _native_binary_path, is_admin

BINARY = _native_binary_path()

pytestmark = [
    pytest.mark.skipif(BINARY is None, reason="native binary not built"),
    pytest.mark.skipif(not is_admin(), reason="ETW capture requires Administrator"),
]


def test_real_capture_emits_events() -> None:
    """Hello sentinel + at least one event within 5 seconds of file activity."""
    proc = subprocess.Popen(
        [
            str(BINARY),
            "--pid",
            str(os.getpid()),
            "--session-name",
            f"ActivityTrackerTest-{os.getpid()}",
            "--stats-interval-ms",
            "500",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        # Read the hello first.
        first = proc.stdout.readline()
        hello = json.loads(first)
        assert hello["type"] == "hello"
        assert hello["version"] == "1.0"
        assert hello["target_pid"] == os.getpid()

        # Generate file activity to provoke events.
        deadline = time.monotonic() + 5.0
        events: list[dict] = []
        while time.monotonic() < deadline and len(events) < 1:
            tmp = Path(os.environ.get("TEMP", ".")) / f"smoke-{os.getpid()}.tmp"
            tmp.write_bytes(b"hello")
            tmp.unlink(missing_ok=True)
            line = proc.stdout.readline()
            if not line:
                break
            try:
                payload = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if payload.get("type") not in ("hello", "stats"):
                events.append(payload)

        assert events, "no event lines emitted within timeout — ETW capture broken?"
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()

"""Unit tests for ``service.capture_service.CaptureService``.

These tests do NOT spawn the real native binary — they patch
``subprocess.Popen`` with an in-memory fake whose ``stdout`` is pre-seeded
with JSON lines (hello sentinel, events, stats heartbeats). This lets us
exercise the wrapper's startup handshake, line pump, callback dispatch,
stats heartbeat aggregation, and shutdown ladder without elevation.

A real-binary smoke test lives in ``test_native_smoke_admin.py`` and is
gated behind admin + binary-present checks.
"""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from service.capture_service import CaptureService, CaptureTarget

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def hello_line(version: str = "1.0", session: str = "ActivityTracker-1234-test") -> bytes:
    return (
        json.dumps(
            {
                "type": "hello",
                "version": version,
                "session_name": session,
                "target_pid": 1234,
                "pid": 9999,
                "started_at": "2026-04-28T12:00:00Z",
            }
        )
        + "\n"
    ).encode()


def event_line(
    kind: str = "file",
    operation: str = "create",
    path: str = "C:\\foo.txt",
    pid: int = 1234,
    event_id: str = "test-id",
) -> bytes:
    return (
        json.dumps(
            {
                "id": event_id,
                "ts": "2026-04-28T12:00:01.000Z",
                "kind": kind,
                "operation": operation,
                "pid": pid,
                "ppid": None,
                "path": path,
                "target": None,
                "details": {},
            }
        )
        + "\n"
    ).encode()


def stats_line(
    tracked_pids: int = 1,
    cache_size: int = 0,
    errors: int = 0,
    last_event_at: str = "",
) -> bytes:
    return (
        json.dumps(
            {
                "type": "stats",
                "tracked_pids": tracked_pids,
                "file_object_cache_size": cache_size,
                "errors": errors,
                "last_event_at": last_event_at,
                "ts": "2026-04-28T12:00:02.000Z",
            }
        )
        + "\n"
    ).encode()


def make_fake_popen(
    lines: list[bytes],
    stderr_lines: tuple[bytes, ...] = (),
    poll_initially_dead: bool = False,
) -> tuple[MagicMock, MagicMock]:
    """Build a fake (popen_factory, fake_proc).

    ``lines`` is the full stdout sequence (hello + any subsequent JSON lines).
    ``poll_initially_dead`` forces ``poll()`` to report exit-code 0 from the
    very first call — used to test the "exited before hello" path.
    """
    stdout = io.BytesIO(b"".join(lines))
    stderr = io.BytesIO(b"".join(stderr_lines))

    fake = MagicMock()
    fake.stdout = stdout
    fake.stderr = stderr
    fake.stdin = io.BytesIO()
    fake.returncode = 0 if poll_initially_dead else None
    if poll_initially_dead:
        fake.poll = MagicMock(return_value=0)
    else:
        fake.poll = MagicMock(return_value=None)
    fake.wait = MagicMock(return_value=0)
    fake.terminate = MagicMock()
    fake.kill = MagicMock()
    return MagicMock(return_value=fake), fake


def wait_for(predicate, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until it returns truthy or the deadline lapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch admin + binary lookup so ``start()`` reaches the spawn step."""
    binary = tmp_path / "tracker_capture.exe"
    binary.write_bytes(b"")  # exists but empty — that's fine, Popen is mocked.
    from service import capture_service as svc_mod

    monkeypatch.setattr(svc_mod, "_native_binary_path", lambda: binary)
    monkeypatch.setattr(svc_mod, "is_admin", lambda: True)
    return binary


def _make_service(
    on_event=None, pid: int = 1234, exe_path: str = "C:/x.exe"
) -> CaptureService:
    return CaptureService(
        target=CaptureTarget(exe_path=exe_path, pid=pid),
        on_event=on_event or (lambda _payload: None),
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_hello_handshake_ok(fake_binary: Path) -> None:
    """A valid hello line completes ``start()`` and engine reports ``native``."""
    factory, fake = make_fake_popen([hello_line()])
    with patch("subprocess.Popen", factory):
        svc = _make_service()
        svc.start()
        try:
            assert svc._session_started_at == "2026-04-28T12:00:00Z"
            stats = svc.stats()
            assert stats["engine"] == "native"
            assert stats["target_pid"] == 1234
            assert stats["session_name"] == "ActivityTracker-1234-test"
        finally:
            svc.stop()
        # Threads should be reaped.
        for t in svc._threads:
            assert not t.is_alive()


def test_version_mismatch_raises(fake_binary: Path) -> None:
    """A hello with the wrong protocol version aborts ``start()``."""
    factory, fake = make_fake_popen([hello_line(version="2.0")])
    with patch("subprocess.Popen", factory):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="version"):
            svc.start()
    fake.terminate.assert_called()


def test_premature_exit_before_hello(fake_binary: Path) -> None:
    """Process exiting with no stdout output raises a clear RuntimeError."""
    factory, fake = make_fake_popen(
        [], stderr_lines=(b"failed to start trace: 5\n",), poll_initially_dead=True
    )
    with patch("subprocess.Popen", factory):
        svc = _make_service()
        with pytest.raises(RuntimeError, match="hello sentinel"):
            svc.start()


def test_event_lines_dispatch_to_callback(fake_binary: Path) -> None:
    """File and registry events arrive in order; ``timestamp`` is aliased."""
    received: list[dict[str, Any]] = []
    lock = threading.Lock()

    def on_event(payload: dict[str, Any]) -> None:
        with lock:
            received.append(payload)

    lines = [
        hello_line(),
        event_line(kind="file", operation="create", event_id="e1"),
        event_line(kind="registry", operation="set", event_id="e2"),
    ]
    factory, _fake = make_fake_popen(lines)
    with patch("subprocess.Popen", factory):
        svc = _make_service(on_event=on_event)
        svc.start()
        try:
            assert wait_for(lambda: len(received) >= 2, timeout=2.0)
        finally:
            svc.stop()

    assert [e["id"] for e in received] == ["e1", "e2"]
    assert received[0]["kind"] == "file"
    assert received[1]["kind"] == "registry"
    # ``timestamp`` should be aliased from ``ts`` by the wrapper.
    for ev in received:
        assert "timestamp" in ev
        assert ev["timestamp"] == ev["ts"]


def test_stats_heartbeat_updates_cache(fake_binary: Path) -> None:
    """Stats lines update tracked_pids / cache_size / errors / last_event_at."""
    lines = [
        hello_line(),
        stats_line(
            tracked_pids=5, cache_size=12, errors=1, last_event_at="2026-04-28T12:00:01Z"
        ),
        stats_line(
            tracked_pids=7, cache_size=20, errors=2, last_event_at="2026-04-28T12:00:02Z"
        ),
    ]
    factory, _fake = make_fake_popen(lines)
    with patch("subprocess.Popen", factory):
        svc = _make_service()
        svc.start()
        try:
            assert wait_for(lambda: svc.stats().get("tracked_pids") == 7, timeout=2.0)
            stats = svc.stats()
            assert stats["tracked_pids"] == 7
            assert stats["file_object_cache_size"] == 20
            # ``errors`` aggregates wrapper-side errors with native-reported ones.
            assert stats["errors"] >= 2
            assert stats["last_event_at"] == "2026-04-28T12:00:02Z"
        finally:
            svc.stop()


def test_bad_json_line_increments_error_counter(fake_binary: Path) -> None:
    """Malformed lines bump the error counter without skipping good events."""
    received: list[dict[str, Any]] = []
    lock = threading.Lock()

    def on_event(payload: dict[str, Any]) -> None:
        with lock:
            received.append(payload)

    lines = [
        hello_line(),
        b"not json\n",
        event_line(event_id="good"),
    ]
    factory, _fake = make_fake_popen(lines)
    with patch("subprocess.Popen", factory):
        svc = _make_service(on_event=on_event)
        svc.start()
        try:
            assert wait_for(lambda: len(received) >= 1, timeout=2.0)
            # Wait a tick so the bad line is also processed.
            assert wait_for(lambda: svc._error_count >= 1, timeout=2.0)
        finally:
            svc.stop()

    assert len(received) == 1
    assert received[0]["id"] == "good"
    assert svc._error_count >= 1


def test_stop_is_idempotent(fake_binary: Path) -> None:
    """Calling ``stop()`` twice should never raise."""
    factory, _fake = make_fake_popen([hello_line()])
    with patch("subprocess.Popen", factory):
        svc = _make_service()
        svc.start()
        svc.stop()
        # Second stop is a no-op.
        svc.stop()
    for t in svc._threads:
        assert not t.is_alive()


def test_admin_check_blocks_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-admin invocation must raise PermissionError before any spawn."""
    from service import capture_service as svc_mod

    binary = tmp_path / "tracker_capture.exe"
    binary.write_bytes(b"")
    monkeypatch.setattr(svc_mod, "_native_binary_path", lambda: binary)
    monkeypatch.setattr(svc_mod, "is_admin", lambda: False)

    svc = _make_service()
    with pytest.raises(PermissionError, match="Administrator"):
        svc.start()


def test_missing_binary_raises_with_build_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing binary surfaces the BUILD_HINT (cmake instructions)."""
    from service import capture_service as svc_mod

    monkeypatch.setattr(svc_mod, "_native_binary_path", lambda: None)
    monkeypatch.setattr(svc_mod, "is_admin", lambda: True)

    svc = _make_service()
    with pytest.raises(RuntimeError, match="Native binary not found") as excinfo:
        svc.start()
    assert "cmake" in str(excinfo.value)


def test_note_dropped_accumulates() -> None:
    """``note_dropped`` adds to the wrapper-side drop counter."""
    svc = _make_service()
    svc.note_dropped(3)
    svc.note_dropped(2)
    assert svc.stats()["dropped"] == 5

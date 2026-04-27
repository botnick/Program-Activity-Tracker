"""Tests for the native ETW capture engine integration.

The native subprocess itself is not started here — ``CaptureService.start``
is exercised only up to the point where it discovers (or fails to discover)
the native binary. The first test (``test_binary_built``) requires a Windows
build of the native engine to be present; it is skipped otherwise so the
suite still passes on CI / Linux developer machines.
"""

from __future__ import annotations

import sys

import pytest

from service import capture_service as cs
from service.capture_service import (
    CaptureService,
    CaptureTarget,
    _native_binary_path,
)


def _make_service(target_pid: int = 4321) -> CaptureService:
    return CaptureService(
        target=CaptureTarget(exe_path="C:/x.exe", pid=target_pid),
        on_event=lambda _payload: None,
    )


def test_binary_built() -> None:
    """tracker_capture.exe should exist after a successful Windows build."""
    if sys.platform != "win32":
        pytest.skip("native binary is Windows-only")
    binary = _native_binary_path()
    if binary is None:
        pytest.skip(
            "native binary not built; run cmake under service/native "
            "(see service/native/README.md)"
        )
    assert binary.exists()
    assert binary.stat().st_size > 0


def test_native_engine_missing_binary_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``start()`` raises a clear RuntimeError when the binary is absent."""
    monkeypatch.setattr(cs, "_native_binary_path", lambda: None)
    monkeypatch.setattr(cs, "is_admin", lambda: True)

    svc = _make_service()
    with pytest.raises(RuntimeError, match="Native binary not found"):
        svc.start()

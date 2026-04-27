"""Tests for the native ETW capture engine integration.

These exercise the dispatch logic in ``service.capture_service.CaptureService``
that picks between the native ``tracker_capture.exe`` binary and the legacy
``pywintrace`` backend. The native subprocess itself is not started here —
``_start_native`` and ``_start_pywintrace`` are monkey-patched.

The first test (``test_binary_built``) requires a Windows build of the
native engine to be present; it is skipped otherwise so the suite still
passes on CI / Linux developer machines.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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


def test_capture_service_picks_native_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a native binary available and engine=auto, the native path runs."""
    monkeypatch.setenv("TRACKER_CAPTURE_ENGINE", "auto")
    monkeypatch.setattr(
        cs,
        "_native_binary_path",
        lambda: Path(r"C:\fake\tracker_capture.exe"),
    )

    called: list[str] = []
    monkeypatch.setattr(
        CaptureService,
        "_start_native",
        lambda self, binary: called.append(f"native:{binary}"),
    )
    monkeypatch.setattr(
        CaptureService,
        "_start_pywintrace",
        lambda self: called.append("python"),
    )

    svc = _make_service()
    svc.start()

    assert called == [r"native:C:\fake\tracker_capture.exe"]


def test_capture_service_falls_back_to_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto + no binary -> pywintrace path runs."""
    monkeypatch.setenv("TRACKER_CAPTURE_ENGINE", "auto")
    monkeypatch.setattr(cs, "_native_binary_path", lambda: None)

    called: list[str] = []
    monkeypatch.setattr(
        CaptureService,
        "_start_native",
        lambda self, binary: called.append("native"),
    )
    monkeypatch.setattr(
        CaptureService,
        "_start_pywintrace",
        lambda self: called.append("python"),
    )

    svc = _make_service()
    svc.start()

    assert called == ["python"]


def test_native_engine_setting_python_forces_pywintrace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TRACKER_CAPTURE_ENGINE=python`` skips the native path entirely."""
    monkeypatch.setenv("TRACKER_CAPTURE_ENGINE", "python")
    monkeypatch.setattr(
        cs,
        "_native_binary_path",
        lambda: Path(r"C:\fake\tracker_capture.exe"),
    )

    called: list[str] = []
    monkeypatch.setattr(
        CaptureService,
        "_start_native",
        lambda self, binary: called.append("native"),
    )
    monkeypatch.setattr(
        CaptureService,
        "_start_pywintrace",
        lambda self: called.append("python"),
    )

    svc = _make_service()
    svc.start()

    assert called == ["python"]


def test_native_engine_missing_binary_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TRACKER_CAPTURE_ENGINE=native`` + no binary should error clearly."""
    monkeypatch.setenv("TRACKER_CAPTURE_ENGINE", "native")
    monkeypatch.setattr(cs, "_native_binary_path", lambda: None)

    called: list[str] = []
    monkeypatch.setattr(
        CaptureService,
        "_start_native",
        lambda self, binary: called.append("native"),
    )
    monkeypatch.setattr(
        CaptureService,
        "_start_pywintrace",
        lambda self: called.append("python"),
    )

    svc = _make_service()
    with pytest.raises(RuntimeError, match="Native capture binary"):
        svc.start()
    assert called == []


def test_stats_reports_engine() -> None:
    """``stats()['engine']`` reflects the active backend."""
    svc = _make_service()
    stats: dict[str, Any] = svc.stats()
    # Pre-start: engine label is ``"none"`` (no backend selected yet).
    assert "engine" in stats
    assert stats["engine"] in {"none", "native", "python"}

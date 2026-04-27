"""Unit tests for ``service.capture_service.CaptureService``.

These tests bypass ``CaptureService.start()`` (which needs Administrator
+ a real ETW session) and exercise the event pipeline by calling the
sync ``_on_etw_event`` directly with synthetic event tuples shaped like
what ``pywintrace`` produces.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

pytest.importorskip("etw")

from service.capture_service import CaptureService, CaptureTarget
from service import etw_cleanup
from tests.fixtures import etw_events as ev


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(
    target_pid: int = 1234,
    pid_create_time: float | None = None,
) -> tuple[CaptureService, list[dict[str, Any]]]:
    """Build a CaptureService that bypasses ``start()`` (no admin / ETW needed)."""
    captured: list[dict[str, Any]] = []
    svc = CaptureService(
        target=CaptureTarget(
            exe_path="C:/x.exe",
            pid=target_pid,
            pid_create_time=pid_create_time,
        ),
        on_event=lambda payload: captured.append(payload),
    )
    return svc, captured


def _file_create_event(file_object: int, filename: str, pid: int = 1234) -> tuple[int, dict[str, Any]]:
    return (
        12,
        {
            "EventHeader": ev.make_header(ev.PROVIDER_FILE, pid),
            "Task Name": "Create",
            "FileObject": file_object,
            "FileName": filename,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_lru_eviction() -> None:
    svc, _captured = make_service()
    # Tighten the cap on this instance.
    svc._file_object_cache_cap = 3

    # Insert four entries — oldest should fall out.
    svc._track_file_object(*_file_create_event(0x1, r"\Device\HarddiskVolume1\a"))
    svc._track_file_object(*_file_create_event(0x2, r"\Device\HarddiskVolume1\b"))
    svc._track_file_object(*_file_create_event(0x3, r"\Device\HarddiskVolume1\c"))

    # Touch entry 0x1 so it becomes most-recent.
    _ = svc._resolve_file_path({"FileObject": 0x1})

    svc._track_file_object(*_file_create_event(0x4, r"\Device\HarddiskVolume1\d"))

    assert 0x1 in svc._file_object_paths, "recently accessed entry should survive"
    assert 0x2 not in svc._file_object_paths, "oldest entry should have been evicted"
    assert 0x3 in svc._file_object_paths
    assert 0x4 in svc._file_object_paths
    assert len(svc._file_object_paths) == 3


def test_unc_translation() -> None:
    svc, captured = make_service()
    svc._on_etw_event(ev.FILE_CREATE_UNC)

    assert captured, "UNC create event should be captured"
    path = captured[-1]["path"]
    assert isinstance(path, str)
    # \Device\Mup\server\share\notes.docx -> \\server\share\notes.docx
    assert path.startswith(r"\\server\share"), f"unexpected UNC translation: {path!r}"


def test_drive_translation() -> None:
    svc, captured = make_service()
    svc._dos_map = [(r"\device\harddiskvolume3", "X:")]
    svc._on_etw_event(ev.FILE_CREATE)

    assert captured
    path = captured[-1]["path"]
    assert path is not None
    assert path.startswith("X:\\"), f"expected DOS-letter translation, got {path!r}"


def test_descendant_tracking() -> None:
    svc, captured = make_service()
    svc._on_etw_event(ev.PROCESS_START_CHILD)

    assert 9999 in svc._tracked_pids, "child pid should be tracked after ProcessStart"

    # The newly-tracked child issues a file create.
    child_create = (
        12,
        {
            "EventHeader": ev.make_header(ev.PROVIDER_FILE, 9999),
            "Task Name": "Create",
            "FileObject": 0xCAFE0001,
            "FileName": r"\Device\HarddiskVolume3\Users\test\child.bin",
        },
    )
    captured.clear()
    svc._on_etw_event(child_create)
    assert captured, "file event from descendant pid should be captured"
    assert captured[-1]["pid"] == 9999


def test_pid_reuse_rejection() -> None:
    svc, captured = make_service(pid_create_time=100.0)

    with patch("service.capture_service.psutil.Process") as mock_proc:
        mock_proc.return_value.create_time.return_value = 200.0
        svc._on_etw_event(ev.FILE_CREATE)

    assert not captured, "event from PID with mismatched create_time must be rejected"


def test_pid_reuse_accepts_matching_create_time() -> None:
    svc, captured = make_service(pid_create_time=100.0)

    with patch("service.capture_service.psutil.Process") as mock_proc:
        mock_proc.return_value.create_time.return_value = 100.0
        svc._on_etw_event(ev.FILE_CREATE)

    assert captured, "event from PID with matching create_time should be accepted"


def test_file_object_resolution() -> None:
    svc, captured = make_service()
    svc._on_etw_event(ev.FILE_CREATE)
    svc._on_etw_event(ev.FILE_WRITE)

    assert len(captured) == 2
    create_path = captured[0]["path"]
    write_path = captured[1]["path"]
    assert write_path is not None
    assert write_path == create_path, (
        f"Write event should resolve via FileObject cache to the Create's path "
        f"(create={create_path!r}, write={write_path!r})"
    )


def test_normalize_kinds() -> None:
    svc, captured = make_service()
    svc._on_etw_event(ev.FILE_CREATE)
    svc._on_etw_event(ev.REGISTRY_SET_VALUE)
    svc._on_etw_event(ev.PROCESS_START_CHILD)
    svc._on_etw_event(ev.TCP_CONNECT_V4)

    kinds = [e["kind"] for e in captured]
    operations = [e["operation"] for e in captured]
    assert kinds == ["file", "registry", "process", "network"]
    assert operations == ["create", "set_value", "start", "tcp_connect_v4"]


def test_network_v4_address_format() -> None:
    svc, captured = make_service()
    svc._on_etw_event(ev.TCP_CONNECT_V4)

    assert captured
    target = captured[-1]["target"]
    assert isinstance(target, str)
    # 0x0100007F little-endian -> 127.0.0.1; port is whatever int we passed.
    assert target.startswith("127.0.0.1:"), f"unexpected target format: {target!r}"


def test_error_sample_rate(caplog: pytest.LogCaptureFixture) -> None:
    svc, _captured = make_service()

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic")

    svc._normalize = _boom  # type: ignore[assignment]

    caplog.set_level(logging.WARNING, logger="service.capture_service")
    for _ in range(100):
        svc._on_etw_event(ev.FILE_CREATE)

    assert svc._error_count == 100
    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "service.capture_service"
    ]
    assert len(warning_records) == 1, (
        f"expected exactly 1 sampled warning, got {len(warning_records)}"
    )


def test_stats_shape() -> None:
    svc, _ = make_service()
    keys = set(svc.stats().keys())
    assert keys == {
        "session_name",
        "target_pid",
        "tracked_pids",
        "file_object_cache_size",
        "errors",
        "dropped",
        "last_event_at",
    }


def test_note_dropped() -> None:
    svc, _ = make_service()
    svc.note_dropped(5)
    assert svc.stats()["dropped"] == 5
    svc.note_dropped()
    assert svc.stats()["dropped"] == 6


def test_etw_cleanup_handles_missing_logman(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_fnf(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("logman")

    monkeypatch.setattr(etw_cleanup.subprocess, "run", _raise_fnf)
    result = etw_cleanup.sweep_orphan_sessions()
    assert result == []


def test_etw_cleanup_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="logman", timeout=10)

    monkeypatch.setattr(etw_cleanup.subprocess, "run", _raise_timeout)
    assert etw_cleanup.sweep_orphan_sessions() == []

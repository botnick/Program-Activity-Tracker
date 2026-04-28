"""Tests for the native --list-processes mode and its /api/processes binding.

Two halves:
- The first two tests shell out to the freshly built tracker_capture binary
  (skipped if it isn't on disk yet) and check that it emits valid NDJSON
  including the test runner's own pid.
- The last two tests stub _list_processes_native to verify the HTTP handler
  honours both the native-success and native-missing paths.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from service.capture_service import _native_binary_path

BINARY = _native_binary_path()


@pytest.mark.skipif(BINARY is None, reason="native binary not built")
def test_list_processes_emits_ndjson() -> None:
    """`--list-processes` prints one JSON object per line on stdout."""
    result = subprocess.run(
        [str(BINARY), "--list-processes"],
        capture_output=True,
        text=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    # Any modern Windows host has way more than five processes.
    assert len(lines) > 5
    for raw in lines[:50]:
        payload = json.loads(raw.decode("utf-8"))
        assert "pid" in payload
        assert "ppid" in payload
        assert "name" in payload
        # exe / username may be empty for access-denied processes.
        assert isinstance(payload.get("exe", ""), str)
        assert isinstance(payload.get("username", ""), str)


@pytest.mark.skipif(BINARY is None, reason="native binary not built")
def test_list_processes_includes_self() -> None:
    """Our own python.exe must be in the snapshot."""
    result = subprocess.run(
        [str(BINARY), "--list-processes"],
        capture_output=True,
        text=False,
        timeout=10,
    )
    assert result.returncode == 0
    pids = [
        json.loads(ln.decode("utf-8"))["pid"]
        for ln in result.stdout.splitlines()
        if ln.strip()
    ]
    assert os.getpid() in pids


def test_api_processes_falls_back_when_binary_missing(monkeypatch) -> None:
    """If `_list_processes_native` returns None, /api/processes uses psutil."""
    from fastapi.testclient import TestClient

    from backend.app import api_routes
    from backend.app import main as main_mod

    monkeypatch.setattr(api_routes, "_list_processes_native", lambda: None)

    with TestClient(main_mod.app) as c:
        r = c.get("/api/processes")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "admin" in body
        # psutil fallback always finds something on a real host.
        assert len(body["items"]) > 0


def test_api_processes_uses_native_when_present(monkeypatch) -> None:
    """When `_list_processes_native` returns rows, they are served as-is."""
    from fastapi.testclient import TestClient

    from backend.app import api_routes
    from backend.app import main as main_mod

    fake_rows = [
        # pid > 4 — handler filters out kernel pseudo-processes (pid 0/4).
        {
            "pid": 1234,
            "ppid": 100,
            "name": "fake.exe",
            "exe": "C:\\fake.exe",
            "username": "X\\Y",
        }
    ]
    monkeypatch.setattr(
        api_routes, "_list_processes_native", lambda: fake_rows
    )

    with TestClient(main_mod.app) as c:
        r = c.get("/api/processes")
        assert r.status_code == 200
        items = r.json()["items"]
        assert any(i["name"] == "fake.exe" for i in items)

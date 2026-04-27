"""Real-binary protocol tests for ``tracker_capture.exe``.

These tests do **not** require Administrator: they exercise paths that
either succeed (``--version``) or that fail before the trace session is
actually opened (``--help``, missing ``--pid``). The whole module is
skipped when the binary hasn't been built.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from service.capture_service import _native_binary_path

BINARY = _native_binary_path()
pytestmark = pytest.mark.skipif(BINARY is None, reason="native binary not built")


def test_version_flag() -> None:
    """``--version`` prints ``tracker_capture <version>`` and exits 0."""
    result = subprocess.run(
        [str(BINARY), "--version"], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    assert "tracker_capture" in result.stdout
    assert "1.0" in result.stdout


def test_help_flag_exits_with_code_2() -> None:
    """``--help`` should print a usage banner and exit with code 2."""
    result = subprocess.run(
        [str(BINARY), "--help"], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 2
    output = (result.stdout + result.stderr).lower()
    assert "--pid" in output


def test_no_args_exits_nonzero() -> None:
    """Running with no args must fail (missing required ``--pid``)."""
    result = subprocess.run(
        [str(BINARY)], capture_output=True, text=True, timeout=5
    )
    assert result.returncode != 0


def test_pid_required_error() -> None:
    """Spawning ``--pid 1`` without admin should fail before the hello sentinel.

    On a non-admin shell ``EtwSession::Start`` returns ``ERROR_ACCESS_DENIED``
    (5) and the binary exits with code 3 — *no* hello line is emitted. On an
    admin shell this would actually start a session, so the test is loose
    enough to accept that case (a single hello-shaped line on stdout).
    """
    result = subprocess.run(
        [str(BINARY), "--pid", "1"], capture_output=True, text=True, timeout=5
    )
    assert result.returncode != 0
    if result.stdout.strip():
        # Some defensive setups may still emit hello — accept that.
        first = result.stdout.strip().splitlines()[0]
        try:
            payload = json.loads(first)
        except (ValueError, json.JSONDecodeError):
            pytest.fail(f"Unexpected stdout: {first[:200]!r}")
        else:
            assert payload.get("type") == "hello"

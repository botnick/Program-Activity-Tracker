"""Integration test: drive the real backend in-process via httpx.ASGITransport.

This avoids spawning uvicorn — the FastAPI app is mounted directly on an
httpx transport so every TrackerClient call hits the live code path. Skips if
the backend can't be imported in this environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

# Make sure the repo root is importable for ``backend.app.main``.
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

try:  # pragma: no cover - import guard
    from backend.app.main import create_app  # noqa: E402
except Exception as exc:  # noqa: BLE001
    create_app = None
    _import_error = exc
else:
    _import_error = None


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def live_client(monkeypatch):
    if create_app is None:
        pytest.skip(f"backend not importable: {_import_error}")

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    base = "http://testserver"

    from mcp_tracker.client import TrackerClient
    from mcp_tracker.config import get_settings

    monkeypatch.setenv("MCP_TRACKER_URL", base)
    get_settings.cache_clear()

    def _patched(self):
        return httpx.AsyncClient(
            transport=transport,
            base_url=base,
            timeout=self._timeout,
            headers=self._headers,
        )

    monkeypatch.setattr(TrackerClient, "_make_client", _patched, raising=True)

    tc = TrackerClient(base_url=base)
    yield tc, app, transport


async def test_integration_health(live_client):
    tc, _, _ = live_client
    h = await tc.health()
    assert "status" in h
    assert "captures" in h


async def test_integration_session_lifecycle(live_client):
    import os

    from mcp_tracker import tools

    tc, _, _ = live_client
    sessions_before = await tools.list_sessions(tc)
    initial_count = len(sessions_before["items"])

    # Start a session by pid against this test process (we know it's running).
    # Without admin the tracker still creates the session with capture='needs_admin'.
    started = await tools.start_session(tc, pid=os.getpid())
    sid = started["session_id"]
    assert started["pid"] == os.getpid()

    sessions_after = await tools.list_sessions(tc)
    assert len(sessions_after["items"]) == initial_count + 1

    # query_events should not raise (the seeded session may have events).
    events = await tools.query_events(tc, session_id=sid, limit=10)
    assert "items" in events

    # Stop the session.
    stopped = await tools.stop_session(tc, sid)
    assert stopped.get("status") == "stopped"


async def test_integration_processes(live_client):
    tc, _, _ = live_client
    procs = await tc.processes()
    assert "items" in procs
    # The host should always have at least one process.
    assert isinstance(procs["items"], list)

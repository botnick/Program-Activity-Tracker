"""Shared fixtures for the mcp_tracker test suite."""

from __future__ import annotations

import os

import pytest
import respx


BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Make sure each test starts with a fresh settings cache."""
    from mcp_tracker.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def env_tracker_url(monkeypatch):
    monkeypatch.setenv("MCP_TRACKER_URL", BASE_URL)
    monkeypatch.delenv("MCP_TRACKER_TIMEOUT", raising=False)
    monkeypatch.delenv("MCP_TRACKER_TOKEN", raising=False)
    monkeypatch.delenv("MCP_TRACKER_ALLOW_EMIT", raising=False)
    yield


@pytest.fixture
def mock_tracker(env_tracker_url):
    """A respx mock router scoped to the tracker base URL."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client(env_tracker_url):
    """A bare TrackerClient pointed at the mock URL."""
    from mcp_tracker.client import TrackerClient

    return TrackerClient()


@pytest.fixture
def downloads_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TRACKER_DOWNLOAD_DIR", str(tmp_path))
    from mcp_tracker.config import get_settings

    get_settings.cache_clear()
    return tmp_path


@pytest.fixture
async def asgi_tracker(monkeypatch):
    """Run the real backend in-process via httpx.ASGITransport.

    Returns ``(client, base_url)`` where ``client`` is a TrackerClient bound to
    an in-memory ASGI transport. Skips if the backend isn't importable in this
    environment.
    """
    from pathlib import Path
    import sys

    # Ensure repo root is importable so ``backend.app.main`` resolves.
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    try:
        from backend.app.main import create_app
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"backend not importable: {exc}")

    import httpx

    from mcp_tracker.client import TrackerClient

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    base = "http://testserver"

    # Patch TrackerClient to use the ASGI transport.
    real_make_client = TrackerClient._make_client

    def _patched(self):
        return httpx.AsyncClient(
            transport=transport,
            base_url=base,
            timeout=self._timeout,
            headers=self._headers,
        )

    monkeypatch.setattr(TrackerClient, "_make_client", _patched, raising=True)

    monkeypatch.setenv("MCP_TRACKER_URL", base)
    from mcp_tracker.config import get_settings

    get_settings.cache_clear()

    tc = TrackerClient(base_url=base)
    # Override the .base_url so streaming export uses the ASGI transport too.
    yield tc, app, transport
    monkeypatch.setattr(TrackerClient, "_make_client", real_make_client, raising=True)

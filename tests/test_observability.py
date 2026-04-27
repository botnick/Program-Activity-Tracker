"""Tests for backend.app.observability.

These tests use a fresh FastAPI app per case (we don't want to depend on
backend.app.main being importable here) and clear ``get_settings``'s lru_cache
between env-var tweaks.

We deliberately do NOT call ``importlib.reload`` on observability, because
prometheus-client's default registry rejects duplicate metric names. Instead
we import the module once and just bust the settings cache when env vars
change — that's what configure_logging() / cors_origins() / metrics_endpoint()
already read at runtime.
"""

from __future__ import annotations

import contextlib
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Each test gets a clean root logger so configure_logging() can re-run.

    The module marks the root logger with a sentinel attribute on success;
    we strip it (and any handlers we added) so tests don't pollute each other.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    # Tear down anything tests installed.
    for h in list(root.handlers):
        if h not in saved_handlers:
            with contextlib.suppress(Exception):
                h.close()
            root.removeHandler(h)
    root.setLevel(saved_level)
    if hasattr(root, "_tracker_logging_configured"):
        delattr(root, "_tracker_logging_configured")


def _refresh_settings():
    """Drop the lru_cache so a freshly monkeypatched env is observed."""
    from backend.app import config
    config.get_settings.cache_clear()


def _obs():
    _refresh_settings()
    import backend.app.observability as obs
    return obs


# ---------------------------------------------------------------------------
# 1. configure_logging idempotent
# ---------------------------------------------------------------------------

def test_configure_logging_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    obs = _obs()

    obs.configure_logging()
    handler_count_after_first = len(logging.getLogger().handlers)

    obs.configure_logging()
    obs.configure_logging()
    handler_count_after_more = len(logging.getLogger().handlers)

    assert handler_count_after_first == handler_count_after_more
    assert handler_count_after_first >= 2  # at least console + file


# ---------------------------------------------------------------------------
# 2. log_dir created from settings
# ---------------------------------------------------------------------------

def test_log_dir_created(tmp_path, monkeypatch):
    target = tmp_path / "logs_under_test"
    monkeypatch.setenv("TRACKER_LOG_DIR", str(target))
    obs = _obs()

    obs.configure_logging()
    log_file = target / "tracker.log"
    assert target.exists() and target.is_dir()
    assert log_file.exists()


# ---------------------------------------------------------------------------
# 3. trace id contextvar
# ---------------------------------------------------------------------------

def test_trace_id_contextvar(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    obs = _obs()

    assert obs.get_trace_id() is None
    token = obs.set_trace_id("abc")
    try:
        assert obs.get_trace_id() == "abc"
    finally:
        # Token is a contextvars.Token; reset via the contextvar directly.
        obs._trace_id_var.reset(token)
    assert obs.get_trace_id() is None


# ---------------------------------------------------------------------------
# 4. is_safe_exe_path
# ---------------------------------------------------------------------------

def test_is_safe_exe_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    obs = _obs()

    assert obs.is_safe_exe_path(r"C:\Windows\notepad.exe") is True
    assert obs.is_safe_exe_path(r"C:/Windows/notepad.exe") is True

    assert obs.is_safe_exe_path(r"..\foo.exe") is False
    assert obs.is_safe_exe_path("/etc/passwd") is False
    assert obs.is_safe_exe_path(r"\\server\share\foo.exe") is False
    assert obs.is_safe_exe_path("") is False
    assert obs.is_safe_exe_path("foo.exe") is False


# ---------------------------------------------------------------------------
# 5. cors_origins returns list
# ---------------------------------------------------------------------------

def test_cors_origins_returns_list(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("TRACKER_CORS_ORIGINS", '["http://example.com"]')
    from backend.app import config
    config.get_settings.cache_clear()
    from backend.app.observability import cors_origins

    assert cors_origins() == ["http://example.com"]


# ---------------------------------------------------------------------------
# 6. /metrics endpoint
# ---------------------------------------------------------------------------

def test_metrics_endpoint_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("TRACKER_METRICS_ENABLED", "true")
    obs = _obs()

    app = FastAPI()
    app.include_router(obs.router)
    client = TestClient(app)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")


def test_metrics_endpoint_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("TRACKER_METRICS_ENABLED", "false")
    obs = _obs()

    app = FastAPI()
    app.include_router(obs.router)
    client = TestClient(app)

    resp = client.get("/metrics")
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# 7. /api/health shape
# ---------------------------------------------------------------------------

def test_health_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    obs = _obs()

    app = FastAPI()
    app.include_router(obs.router)
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    expected_keys = {
        "status",
        "admin",
        "uptime_seconds",
        "sessions_live",
        "sessions_total",
        "events_buffered",
        "subscribers",
        "captures",
        "log_dir",
    }
    assert expected_keys.issubset(body.keys())
    assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# 8. RequestTraceMiddleware sets / honors X-Trace-Id
# ---------------------------------------------------------------------------

def test_request_middleware_sets_trace_id(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path))
    obs = _obs()

    app = FastAPI()
    app.add_middleware(obs.RequestTraceMiddleware)

    @app.get("/ping")
    def _ping():
        return {}

    client = TestClient(app)

    # 8a: server generates a trace id when client does not supply one.
    resp = client.get("/ping")
    assert resp.status_code == 200
    trace = resp.headers.get("X-Trace-Id")
    assert trace
    assert len(trace) > 0

    # 8b: server echoes a valid client-supplied trace id.
    resp = client.get("/ping", headers={"X-Trace-Id": "abcd"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Trace-Id") == "abcd"

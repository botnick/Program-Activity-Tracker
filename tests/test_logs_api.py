"""Tests for the /api/logs/* endpoints + log stream tail helper."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("TRACKER_DB_PATH", str(tmp_path / "test.db"))
    from backend.app import config

    config.get_settings.cache_clear()
    from backend.app import (
        api_routes as ar_mod,
    )
    from backend.app import (
        main as main_mod,
    )
    from backend.app import (
        observability as obs_mod,
    )
    from backend.app import (
        store as store_mod,
    )

    importlib.reload(store_mod)
    # Reloading observability would clash with prometheus-client's default
    # registry; clear the configured sentinel + handlers instead so the
    # module re-resolves the new TRACKER_LOG_DIR at request time.
    import logging

    root = logging.getLogger()
    if hasattr(root, "_tracker_logging_configured"):
        delattr(root, "_tracker_logging_configured")
    importlib.reload(ar_mod)
    importlib.reload(main_mod)

    # Sanity: ensure obs_mod is the same module reflected by main.
    assert obs_mod is not None

    with TestClient(main_mod.app) as c:
        yield c, tmp_path / "logs"


def test_streams_endpoint_lists_five(client):
    c, _ = client
    r = c.get("/api/logs/streams")
    assert r.status_code == 200
    body = r.json()
    names = [s["name"] for s in body["streams"]]
    assert set(names) == {"tracker", "events", "requests", "errors", "native"}
    assert "log_dir" in body


def test_tail_returns_recent_lines(client):
    c, log_dir = client
    log_dir.mkdir(exist_ok=True)
    (log_dir / "events.log").write_text(
        '{"ts":"2026-04-28T00:00:00Z","level":"INFO","message":"a"}\n'
        '{"ts":"2026-04-28T00:00:01Z","level":"INFO","message":"b"}\n'
        '{"ts":"2026-04-28T00:00:02Z","level":"INFO","message":"c"}\n',
        encoding="utf-8",
    )
    r = c.get("/api/logs/events?tail=2")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert items[-1]["message"] == "c"


def test_unknown_stream_empty(client):
    c, _ = client
    r = c.get("/api/logs/nope?tail=10")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_tail_handles_non_json_lines(client):
    c, log_dir = client
    log_dir.mkdir(exist_ok=True)
    (log_dir / "tracker.log").write_text(
        "not json line 1\nnot json line 2\n", encoding="utf-8"
    )
    r = c.get("/api/logs/tracker?tail=2")
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0].get("raw") is True


def test_tail_query_param_validation(client):
    c, _ = client
    # Below min should 422.
    r = c.get("/api/logs/tracker?tail=0")
    assert r.status_code == 422
    # Above max should 422.
    r = c.get("/api/logs/tracker?tail=10000")
    assert r.status_code == 422

"""End-to-end integration test using FastAPI TestClient.

Covers every public route. Runs without admin: capture returns ``needs_admin``
but all CRUD/query/export/metrics paths still exercise.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TRACKER_LOG_DIR", str(tmp_path / "logs"))
    # Reset cached settings + reload store so the new DB path takes effect.
    from backend.app import config

    config.get_settings.cache_clear()
    import importlib

    from backend.app import store as store_mod

    importlib.reload(store_mod)
    from backend.app import api_routes as ar_mod

    importlib.reload(ar_mod)
    # Do NOT reload observability — prometheus-client's default registry would
    # reject the duplicate metric names. The settings cache_clear() above is
    # enough for it to pick up the new log_dir at request time.
    from backend.app import main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "admin", "uptime_seconds", "sessions_live",
                "sessions_total", "events_buffered", "subscribers", "captures",
                "log_dir"):
        assert key in body
    assert "X-Trace-Id" in r.headers


def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code in (200, 501)


def test_processes_endpoint(client):
    r = client.get("/api/processes")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and isinstance(body["items"], list)
    assert "admin" in body


def test_session_lifecycle_non_admin(client):
    # Create a session against this Python interpreter itself (we know the pid).
    r = client.post("/api/sessions", json={"pid": os.getpid()})
    assert r.status_code == 200
    sess = r.json()
    sid = sess["session_id"]
    assert sess["pid"] == os.getpid()
    # CI runs as admin but without the native binary built, so capture starts
    # then fails immediately. Accept any of the four reasonable outcomes.
    assert sess["capture"] in ("needs_admin", "live", "initializing", "failed")

    # GET list
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert any(s["session_id"] == sid for s in r.json()["items"])

    # Inject a custom event so /events has data without admin.
    r = client.post(f"/api/sessions/{sid}/emit", json={
        "kind": "custom",
        "operation": "test",
        "path": "C:/test/foo.txt",
        "details": {"k": "v"},
    })
    assert r.status_code == 200

    # Flush the SQLite writer so query_events sees it.
    from backend.app.store import store

    store.flush()

    # GET events with filter.
    r = client.get(f"/api/sessions/{sid}/events?kind=custom&limit=10")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    assert items[-1]["kind"] == "custom"

    # Search.
    r = client.get(f"/api/sessions/{sid}/events?q=foo.txt")
    assert r.status_code == 200
    assert any("foo.txt" in (it.get("path") or "") for it in r.json()["items"])

    # Export JSONL.
    r = client.get(f"/api/sessions/{sid}/export?format=jsonl")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-jsonlines")
    body = r.text.strip().splitlines()
    assert len(body) >= 1
    import json as _json

    parsed = _json.loads(body[0])
    assert "kind" in parsed

    # Export CSV.
    r = client.get(f"/api/sessions/{sid}/export?format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.startswith("id,session_id,ts,kind")

    # DELETE.
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


def test_404_on_unknown_session(client):
    r = client.get("/api/sessions/does-not-exist/events")
    assert r.status_code == 404
    r = client.get("/api/sessions/does-not-exist/export?format=jsonl")
    assert r.status_code == 404
    r = client.delete("/api/sessions/does-not-exist")
    assert r.status_code == 404


def test_create_session_requires_pid_or_path(client):
    r = client.post("/api/sessions", json={})
    # Current backend may 400 for missing or 404 for not-found.
    assert r.status_code in (400, 404)


def test_trace_id_propagation(client):
    r = client.get("/api/health", headers={"X-Trace-Id": "deadbeef"})
    assert r.status_code == 200
    assert r.headers.get("X-Trace-Id") == "deadbeef"

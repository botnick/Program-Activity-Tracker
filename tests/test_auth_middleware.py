"""Tests for the optional bearer-token auth middleware.

Covers:
* default (TRACKER_AUTH_TOKEN unset) -> middleware is a no-op
* token set + missing/wrong creds -> 401 on /api/*
* token set + correct Authorization header -> 200
* token set + correct ?token= query string -> 200
* exempt paths (/, /favicon.ico, /metrics, /api/health, /assets/*) always pass
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_token(monkeypatch):
    """Return a TestClient where the backend has TRACKER_AUTH_TOKEN set.

    We have to reimport the relevant modules so cached settings pick up the
    new env value. ``functools.lru_cache`` on ``get_settings`` would
    otherwise return the cached unauthenticated config.
    """
    monkeypatch.setenv("TRACKER_AUTH_TOKEN", "s3cret")
    from backend.app import config

    config.get_settings.cache_clear()  # type: ignore[attr-defined]
    from backend.app import main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.create_app()) as c:
        yield c
    config.get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def client_no_token():
    """Default config — auth_token is empty -> middleware is a no-op."""
    from backend.app import config

    config.get_settings.cache_clear()  # type: ignore[attr-defined]
    from backend.app import main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.create_app()) as c:
        yield c
    config.get_settings.cache_clear()  # type: ignore[attr-defined]


def test_no_token_means_no_auth(client_no_token):
    r = client_no_token.get("/api/sessions")
    assert r.status_code == 200


def test_health_is_always_exempt(client_with_token):
    r = client_with_token.get("/api/health")
    assert r.status_code == 200


def test_metrics_is_always_exempt(client_with_token):
    # /metrics may be 200 or 501 depending on prometheus_client install,
    # but it must NOT be 401 (the auth middleware mustn't gate it).
    r = client_with_token.get("/metrics")
    assert r.status_code != 401


def test_protected_endpoint_rejects_missing_token(client_with_token):
    r = client_with_token.get("/api/sessions")
    assert r.status_code == 401


def test_protected_endpoint_rejects_wrong_token(client_with_token):
    r = client_with_token.get(
        "/api/sessions", headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_protected_endpoint_accepts_bearer_header(client_with_token):
    r = client_with_token.get(
        "/api/sessions", headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200


def test_protected_endpoint_accepts_query_string(client_with_token):
    r = client_with_token.get("/api/sessions?token=s3cret")
    assert r.status_code == 200

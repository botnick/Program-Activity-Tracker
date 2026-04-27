"""Tests for the error mapping layer."""

from __future__ import annotations

import httpx
import pytest

from mcp_tracker.errors import TrackerError, map_http_error


def test_connect_error_message():
    err = map_http_error(httpx.ConnectError("boom"))
    assert isinstance(err, TrackerError)
    assert "Tracker is not reachable" in str(err)


def test_404_message():
    req = httpx.Request("GET", "http://x/api/sessions/x")
    resp = httpx.Response(404, text="not found", request=req)
    err = map_http_error(httpx.HTTPStatusError("404", request=req, response=resp))
    assert "Session not found" in str(err)


def test_status_error_includes_body():
    req = httpx.Request("POST", "http://x/api/sessions")
    resp = httpx.Response(500, text="kaboom internal", request=req)
    err = map_http_error(httpx.HTTPStatusError("500", request=req, response=resp))
    assert "500" in str(err) and "kaboom internal" in str(err)


def test_passthrough_tracker_error():
    err = map_http_error(TrackerError("preserved"))
    assert str(err) == "preserved"


@pytest.mark.asyncio
async def test_tracker_down_message():
    """End-to-end: a TrackerClient pointed at an unreachable URL surfaces the friendly message."""
    from mcp_tracker.client import TrackerClient

    # 127.0.0.1:1 is reliably unbound.
    tc = TrackerClient(base_url="http://127.0.0.1:1", timeout=0.5)
    with pytest.raises(TrackerError) as excinfo:
        await tc.health()
    assert "Tracker is not reachable" in str(excinfo.value)

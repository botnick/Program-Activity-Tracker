"""Tests for backend.app.icons + the /api/processes/icon route."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


def test_cache_key_stable():
    """Case-insensitive Windows paths must collapse to the same key."""
    from backend.app.icons import cache_key

    a = cache_key(r"C:\Windows\System32\notepad.exe")
    b = cache_key(r"c:\windows\system32\notepad.exe")
    assert a == b


def test_cache_key_distinct_for_different_paths():
    from backend.app.icons import cache_key

    a = cache_key(r"C:\Windows\System32\notepad.exe")
    b = cache_key(r"C:\Windows\System32\calc.exe")
    assert a != b


def test_transparent_png_is_valid_png_signature():
    from backend.app.icons import TRANSPARENT_PNG

    assert TRANSPARENT_PNG[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IEND" in TRANSPARENT_PNG


def test_endpoint_rejects_bad_path():
    from backend.app import main

    client = TestClient(main.app)
    r = client.get("/api/processes/icon?exe=" + "../../etc/passwd")
    assert r.status_code == 400


def test_endpoint_rejects_unc_path():
    from backend.app import main

    client = TestClient(main.app)
    r = client.get("/api/processes/icon", params={"exe": r"\\server\share\evil.exe"})
    assert r.status_code == 400


def test_endpoint_rejects_empty_path():
    from backend.app import main

    client = TestClient(main.app)
    r = client.get("/api/processes/icon?exe=")
    # FastAPI Query(min_length=1) rejects with 422; either way it must NOT be 5xx.
    assert r.status_code in (400, 422)


def test_endpoint_falls_back_to_transparent():
    """For a non-existent exe, returns a transparent PNG, not 404."""
    from backend.app import main

    client = TestClient(main.app)
    r = client.get("/api/processes/icon?exe=C:/no_such_file_xyz.exe")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(r.content) > 0


def test_endpoint_sets_cache_headers():
    from backend.app import main

    client = TestClient(main.app)
    r = client.get("/api/processes/icon?exe=C:/no_such_file_xyz.exe")
    assert r.status_code == 200
    assert "max-age" in r.headers.get("cache-control", "")


@pytest.mark.skipif(os.name != "nt", reason="windows-only")
def test_real_notepad_icon():
    notepad = r"C:\Windows\System32\notepad.exe"
    if not os.path.isfile(notepad):
        pytest.skip("notepad not installed")
    from backend.app import main

    client = TestClient(main.app)
    r = client.get(f"/api/processes/icon?exe={notepad}")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    # The 1x1 transparent fallback is well under 200 bytes; a real icon is bigger.
    assert len(r.content) > 200


@pytest.mark.skipif(os.name != "nt", reason="windows-only")
def test_extract_icon_png_direct_notepad():
    """Smoke-test the underlying ctypes extractor without the HTTP wrapper."""
    notepad = r"C:\Windows\System32\notepad.exe"
    if not os.path.isfile(notepad):
        pytest.skip("notepad not installed")
    from backend.app.icons import extract_icon_png

    png = extract_icon_png(notepad)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200


def test_extract_icon_png_returns_none_for_missing_file():
    from backend.app.icons import extract_icon_png

    assert extract_icon_png("C:/definitely_not_here.exe") is None

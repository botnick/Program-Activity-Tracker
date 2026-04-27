"""Streamed CSV/JSONL export → file in the user's Downloads directory."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from .client import TrackerClient
from .config import get_settings
from .errors import map_http_error


async def stream_to_file(
    client: TrackerClient,
    session_id: str,
    format: str,
    **filters,
) -> tuple[Path, int, int]:
    """Stream ``/api/sessions/{id}/export`` to disk.

    Returns ``(path, byte_count, line_count)``. For CSV the header row is
    excluded from ``line_count``.
    """
    settings = get_settings()
    download_dir = Path(settings.download_dir).expanduser()
    download_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = download_dir / f"tracker-{session_id}-{ts}.{format}"

    params = {"format": format}
    params.update({k: v for k, v in filters.items() if v is not None and v != ""})

    byte_count = 0
    line_count = 0
    try:
        async with httpx.AsyncClient(
            base_url=client.base_url,
            timeout=None,
            headers=getattr(client, "_headers", {}) or {},
        ) as http:
            async with http.stream(
                "GET",
                f"/api/sessions/{session_id}/export",
                params=params,
            ) as resp:
                resp.raise_for_status()
                with out.open("wb") as f:
                    async for chunk in resp.aiter_bytes():
                        if not chunk:
                            continue
                        f.write(chunk)
                        byte_count += len(chunk)
                        line_count += chunk.count(b"\n")
    except Exception as exc:  # noqa: BLE001
        raise map_http_error(exc) from exc

    if format == "csv" and line_count > 0:
        # First line is the header row; don't count it as an event.
        line_count -= 1
    return out, byte_count, line_count

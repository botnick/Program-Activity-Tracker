"""Error types and HTTP-error mapping surfaced to MCP clients as tool errors."""

from __future__ import annotations

import httpx


class TrackerError(Exception):
    """Raised by tools/resources when the underlying tracker call fails.

    FastMCP turns uncaught exceptions in tool functions into structured
    ``isError: true`` responses, so callers see the message text.
    """


def map_http_error(exc: Exception) -> TrackerError:
    """Translate an arbitrary exception from an HTTP call into a ``TrackerError``."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return TrackerError(
            "Tracker is not reachable at this URL. Start the backend with "
            "run-elevated.ps1 (admin) or `python -m uvicorn backend.app.main:app`."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 404:
            return TrackerError(
                "Session not found. Use list_sessions to see available ids."
            )
        body = (exc.response.text or "")[:500]
        return TrackerError(f"Tracker returned {status}: {body}")
    if isinstance(exc, TrackerError):
        return exc
    return TrackerError(str(exc))

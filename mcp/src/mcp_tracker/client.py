"""Async HTTP client for the Activity Tracker REST API.

Each public method opens a fresh ``httpx.AsyncClient`` so the client is safe to
use from arbitrary asyncio contexts without lifecycle juggling. The ``stream``
exception is the streaming export, which is exposed as an async generator.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from .config import get_settings
from .errors import TrackerError, map_http_error


class TrackerClient:
    """Thin async wrapper over the tracker HTTP contract."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        token: str | None = None,
    ):
        settings = get_settings()
        self._base = (base_url or settings.tracker_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.timeout
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    # -- internals -------------------------------------------------------

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base,
            timeout=self._timeout,
            headers=self._headers,
        )

    async def _get_json(self, path: str, params: dict | None = None) -> dict:
        try:
            async with self._make_client() as http:
                resp = await http.get(path, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise map_http_error(exc) from exc

    async def _post_json(self, path: str, json_body: dict | None = None) -> dict:
        try:
            async with self._make_client() as http:
                resp = await http.post(path, json=json_body)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise map_http_error(exc) from exc

    async def _delete_json(self, path: str) -> dict:
        try:
            async with self._make_client() as http:
                resp = await http.delete(path)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise map_http_error(exc) from exc

    # -- public API ------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base

    async def health(self) -> dict:
        return await self._get_json("/api/health")

    async def processes(self) -> dict:
        return await self._get_json("/api/processes")

    async def sessions(self) -> dict:
        return await self._get_json("/api/sessions")

    async def session(self, session_id: str) -> dict:
        items = (await self.sessions()).get("items", [])
        for s in items:
            if s.get("session_id") == session_id:
                return s
        raise TrackerError(f"Session not found: {session_id}")

    async def create_session(
        self,
        *,
        pid: int | None = None,
        exe_path: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if pid is not None:
            body["pid"] = pid
        if exe_path is not None:
            body["exe_path"] = exe_path
        return await self._post_json("/api/sessions", body)

    async def stop_session(self, session_id: str) -> dict:
        return await self._delete_json(f"/api/sessions/{session_id}")

    async def events(self, session_id: str, **filters: Any) -> dict:
        params = {k: v for k, v in filters.items() if v is not None and v != ""}
        return await self._get_json(f"/api/sessions/{session_id}/events", params=params)

    async def emit(self, session_id: str, payload: dict) -> dict:
        return await self._post_json(f"/api/sessions/{session_id}/emit", payload)

    async def metrics(self) -> dict:
        """Return Prometheus metrics text, or note that metrics are disabled.

        The backend returns 501 when the optional ``prometheus_client`` package
        isn't installed; in that case we shape a friendly response instead of
        raising.
        """
        try:
            async with self._make_client() as http:
                resp = await http.get("/metrics")
                if resp.status_code == 501:
                    return {"disabled": True, "reason": "prometheus_client not installed"}
                resp.raise_for_status()
                return {
                    "text": resp.text,
                    "content_type": resp.headers.get("content-type", "text/plain"),
                }
        except Exception as exc:  # noqa: BLE001
            raise map_http_error(exc) from exc

    async def stream_export(
        self,
        session_id: str,
        format: str,
        **filters: Any,
    ) -> AsyncIterator[bytes]:
        """Stream the ``/export`` endpoint as bytes.

        Use as ``async for chunk in client.stream_export(...)``.
        """
        params = {"format": format}
        params.update({k: v for k, v in filters.items() if v is not None and v != ""})
        try:
            async with httpx.AsyncClient(
                base_url=self._base, timeout=None, headers=self._headers
            ) as http:
                async with http.stream(
                    "GET",
                    f"/api/sessions/{session_id}/export",
                    params=params,
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception as exc:  # noqa: BLE001
            raise map_http_error(exc) from exc

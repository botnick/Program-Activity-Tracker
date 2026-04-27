"""In-memory session + event storage and pub/sub.

This module owns the data-plane primitives the API layer composes against:

* ``ActivityEvent`` — the canonical event record.
* ``ProcessSelectRequest`` / ``SessionResponse`` — API DTOs.
* ``SessionStore`` — sessions + per-session ring buffer + capture-service handles.
* ``EventHub`` — async fan-out to WebSocket subscribers (drops slow consumers).

A single module-level ``store`` and ``hub`` are exposed; the API router and the
shutdown hook in ``main`` import these singletons. Agent B will swap the
in-memory implementation for SQLite without changing this surface.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from service.capture_service import CaptureService

from .config import get_settings

logger = logging.getLogger("activity_tracker.store")

_settings = get_settings()
EVENT_RING_SIZE: int = _settings.event_ring_size
SUBSCRIBER_QUEUE_SIZE: int = _settings.subscriber_queue_size


class ProcessSelectRequest(BaseModel):
    exe_path: str | None = Field(default=None)
    pid: int | None = Field(default=None)


class SessionResponse(BaseModel):
    session_id: str
    exe_path: str
    pid: int
    created_at: str
    status: str
    capture: str
    capture_error: str | None = None


@dataclass
class ActivityEvent:
    id: str
    session_id: str
    timestamp: str
    kind: str
    pid: int | None = None
    ppid: int | None = None
    path: str | None = None
    target: str | None = None
    operation: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._events: dict[str, deque[ActivityEvent]] = defaultdict(
            lambda: deque(maxlen=EVENT_RING_SIZE)
        )
        self._capture: dict[str, CaptureService] = {}

    def create(
        self,
        exe_path: str,
        pid: int,
        capture_status: str,
        capture_error: str | None,
    ) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "exe_path": exe_path,
            "pid": pid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "tracking" if capture_status == "live" else capture_status,
            "capture": capture_status,
            "capture_error": capture_error,
        }
        self._sessions[session_id] = session
        return session

    def attach_capture(self, session_id: str, service: CaptureService) -> None:
        self._capture[session_id] = service

    def detach_capture(self, session_id: str) -> CaptureService | None:
        return self._capture.pop(session_id, None)

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict[str, Any]]:
        return list(self._sessions.values())

    def add_event(self, event: ActivityEvent) -> None:
        self._events[event.session_id].append(event)

    def events(self, session_id: str) -> list[ActivityEvent]:
        return list(self._events[session_id])

    def all_capture_services(self) -> list[CaptureService]:
        return list(self._capture.values())

    def shutdown(self) -> None:
        """Stop every attached capture service. Best-effort; logs on failure."""
        for service in self.all_capture_services():
            try:
                service.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("capture stop on shutdown failed: %s", exc)


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers[session_id].add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[session_id].discard(queue)

    async def publish(self, session_id: str, payload: dict[str, Any]) -> None:
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._subscribers[session_id]:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._subscribers[session_id].discard(queue)


# Module-level singletons. The API router and shutdown hook bind to these.
store = SessionStore()
hub = EventHub()

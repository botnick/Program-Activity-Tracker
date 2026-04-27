"""Pydantic mirrors of the tracker's HTTP payloads.

These are not strictly required by the FastMCP layer (it accepts plain dicts
back from tools), but they're useful for typing in tests and as living
documentation of the contract this server depends on.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActivityEvent(BaseModel):
    """A single tracker activity event."""

    model_config = ConfigDict(extra="allow")

    id: str
    session_id: str
    timestamp: str | None = None
    ts: str | None = None
    kind: str
    pid: int | None = None
    ppid: int | None = None
    path: str | None = None
    target: str | None = None
    operation: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """A session record returned by ``/api/sessions`` and friends."""

    model_config = ConfigDict(extra="allow")

    session_id: str
    exe_path: str
    pid: int
    created_at: str
    status: str
    capture: str
    capture_error: str | None = None


class ProcessInfo(BaseModel):
    """A row from ``/api/processes``."""

    model_config = ConfigDict(extra="allow")

    pid: int
    ppid: int | None = None
    name: str | None = None
    exe: str | None = None
    username: str | None = None

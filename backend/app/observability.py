"""Observability — filled by Agent C (logging, /metrics, enriched /api/health)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()  # Agent C will register /metrics here


def configure_logging() -> None:
    """No-op for now; Agent C wires structlog."""
    return None

"""Centralized runtime configuration.

All knobs flow through ``Settings``. Environment variables are read with the
``TRACKER_`` prefix (e.g. ``TRACKER_PORT=9000``) and a ``.env`` file at the
repo root is honoured if present. Subsequent agents (storage, observability,
auth) are expected to add new fields here rather than scatter constants.
"""

from __future__ import annotations

import functools

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bind_host: str = "127.0.0.1"
    port: int = 8000
    db_path: str = "events.db"  # relative to repo root unless absolute
    event_ring_size: int = 50_000
    subscriber_queue_size: int = 4096
    file_object_cache_size: int = 100_000
    cors_origins: list[str] = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    log_dir: str = "logs"
    log_level: str = "INFO"
    metrics_enabled: bool = True
    # Retention: drop events older than this many days during periodic vacuum.
    # Set to 0 to disable retention (events grow without bound).
    db_retention_days: int = 30
    # How often the writer thread runs the retention sweep.
    db_retention_check_minutes: int = 60

    # Optional bearer-token auth. When set, every /api/* and /ws/* request
    # must carry the same token in the `Authorization: Bearer <t>` header
    # OR a `?token=<t>` query string. Empty = auth disabled (default, so
    # existing single-user setups don't break). The launcher (tracker.exe)
    # generates a per-launch token automatically and passes it to the
    # browser; manual users can set TRACKER_AUTH_TOKEN themselves.
    auth_token: str = ""

    model_config = SettingsConfigDict(
        env_prefix="TRACKER_",
        env_file=".env",
        extra="ignore",
    )


@functools.lru_cache(1)
def get_settings() -> Settings:
    return Settings()

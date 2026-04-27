"""Settings for the MCP tracker server, sourced from environment variables.

All variables are prefixed with ``MCP_TRACKER_`` so they don't collide with the
backend tracker's own settings (which use the ``ACTIVITY_TRACKER_`` prefix).
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the MCP server."""

    tracker_url: str = "http://127.0.0.1:8000"
    timeout: float = 10.0
    download_dir: str = str(Path.home() / "Downloads")
    allow_emit: bool = False
    token: str = ""
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="MCP_TRACKER_",
        env_file=".env",
        extra="ignore",
    )


@functools.lru_cache(1)
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton.

    Tests should call ``get_settings.cache_clear()`` after monkeypatching env vars
    so the next call re-reads the environment.
    """
    return Settings()

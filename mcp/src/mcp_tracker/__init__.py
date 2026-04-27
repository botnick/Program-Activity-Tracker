"""MCP server exposing the Activity Tracker HTTP API to MCP clients."""

from __future__ import annotations

__version__ = "0.1.0"

# Module-level cache used by resources.py for short-TTL summary caching.
_cache: dict = {}

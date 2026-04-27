"""FastMCP server factory.

Importable so tests can build a server without spawning the stdio transport.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .client import TrackerClient
from .config import get_settings
from .prompts import register_prompts
from .resources import register_resources
from .tools import register_tools


def build_server() -> FastMCP:
    """Construct a fully wired FastMCP server."""
    settings = get_settings()
    mcp = FastMCP("activity-tracker")
    client = TrackerClient(
        base_url=settings.tracker_url,
        timeout=settings.timeout,
        token=settings.token or None,
    )
    register_tools(mcp, client)
    register_resources(mcp, client)
    register_prompts(mcp)
    return mcp

"""Process entry point: ``python -m mcp_tracker``.

Boots a FastMCP server over stdio. Logging goes to stderr only — stdio MCP
servers must keep stdout free of non-protocol bytes.
"""

from __future__ import annotations

import logging
import sys

from .config import get_settings
from .server import build_server


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    mcp = build_server()
    # Default transport is stdio.
    mcp.run()


if __name__ == "__main__":
    main()

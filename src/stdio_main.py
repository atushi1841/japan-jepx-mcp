"""
stdio entry point — MCPB bundle (local distribution) entry.

Used when running as a local MCP server (Claude Desktop / Cursor / Smithery)
via the MCPB bundle, instead of Apify Standby (HTTP).

- transport: FastMCP default stdio (stdout is JSON-RPC only; logs go to stderr)
- no Apify runtime → src/apify_shim.py no-op Actor
- data: bundled seed cache with live-fetch attempt falling back to the seed
"""

from __future__ import annotations

import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.server import get_server  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    server = get_server()
    server.run()  # FastMCP default transport = stdio


if __name__ == "__main__":
    main()

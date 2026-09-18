"""
MCP server entry point — Apify Standby mode enabled.

1. Actor.init() to register with the Apify platform
2. Start a uvicorn HTTP server (Apify-expected port)
3. Wire the FastMCP app (server.py) to the HTTP server + merge the /rest/* wrappers
4. Graceful shutdown on SIGINT
"""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO)

if os.environ.get("APIFY_CONTAINER_PORT"):
    from apify import Actor
else:
    from src.apify_shim import Actor

from src.rest import rest_routes
from src.server import get_server


async def main() -> None:
    await Actor.init()

    port = int(os.environ.get("APIFY_CONTAINER_PORT") or os.environ.get("PORT") or "3000")

    server = get_server()
    app = server.http_app(transport="streamable-http")
    # Merge /rest/* + /openapi.json on the same app for OpenAPI gateways.
    # /mcp (Standby MCP) continues to work as-is.
    app.router.routes.extend(rest_routes())

    try:
        Actor.log.info(f"MCP server starting (port {port})")
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        uvicorn_server = uvicorn.Server(config)
        await uvicorn_server.serve()
    except asyncio.CancelledError:
        Actor.log.info("MCP server stopping")
    finally:
        await Actor.exit()


if __name__ == "__main__":
    asyncio.run(main())

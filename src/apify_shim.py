"""
Apify SDK shim — local / self-hosted fallback (mirrors japan-fuel-price-mcp).

In the Apify Actor runtime the real SDK is used (`from apify import Actor`);
locally (no Apify runtime) Actor.init()/charge() would fail, so this no-op shim
lets the server run standalone.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class _FakeLog:
    def info(self, msg: str, *args, **kwargs) -> None:
        logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        logger.exception(msg, *args, **kwargs)


class Actor:
    log = _FakeLog()

    @classmethod
    async def init(cls, *args, **kwargs) -> None:
        cls.log.info("[shim] Actor.init() no-op")

    @classmethod
    async def exit(cls, *args, **kwargs) -> None:
        cls.log.info("[shim] Actor.exit() no-op")

    @classmethod
    async def get_input(cls) -> dict:
        return {}

    @classmethod
    async def charge(cls, event_title: str, count: int = 1) -> None:
        cls.log.info(f"[shim] Actor.charge({event_title}) no-op")

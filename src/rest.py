"""
REST wrapper — japan-jepx-mcp: expose the JEPX spot queries as plain GET endpoints.

Purpose: RapidAPI / OpenAPI gateways cannot call MCP (streamable-http) directly,
so the same pure-Python functions (src/jepx.py) are made available via JSON
/rest/* routes mounted on the same Starlette app.

Design (mirrors the fuel-price MCP precedent):
- FastMCP http_app (Starlette) + /rest/* + /openapi.json on the same app.
  /mcp stays as the Standby MCP route.
- Authorization is enforced by the Apify platform for all routes (not re-checked here).
- PPE charging happens on the MCP path only (REST is metered by RapidAPI).
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route

from src import jepx

logger = logging.getLogger(__name__)


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _get_int(params: dict[str, str], key: str, default: int) -> int:
    raw = params.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"parameter '{key}' must be an integer, got {raw!r}") from None


def latest_handler(request) -> JSONResponse:
    q = dict(request.query_params)
    try:
        result = jepx.latest_price(q.get("area") or "tokyo")
    except ValueError as e:
        return _err(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("rest latest failed")
        return _err(503, f"data unavailable: {e}")
    return JSONResponse(result)


def date_handler(request) -> JSONResponse:
    q = dict(request.query_params)
    if not q.get("date"):
        return _err(400, "missing required parameter 'date' (YYYY-MM-DD)")
    try:
        result = jepx.price_by_day(q.get("area") or "tokyo", q["date"])
    except ValueError as e:
        return _err(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("rest date failed")
        return _err(503, f"data unavailable: {e}")
    return JSONResponse(result)


def history_handler(request) -> JSONResponse:
    q = dict(request.query_params)
    try:
        result = jepx.history(q.get("area") or "tokyo", _get_int(q, "days", 14))
    except ValueError as e:
        return _err(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("rest history failed")
        return _err(503, f"data unavailable: {e}")
    return JSONResponse(result)


def cheapest_handler(request) -> JSONResponse:
    q = dict(request.query_params)
    try:
        result = jepx.cheapest(q.get("area") or "", _get_int(q, "limit", 5))
    except ValueError as e:
        return _err(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("rest cheapest failed")
        return _err(503, f"data unavailable: {e}")
    return JSONResponse(result)


def areas_handler(request) -> JSONResponse:
    try:
        result = jepx.list_areas()
    except Exception as e:  # noqa: BLE001
        logger.exception("rest areas failed")
        return _err(503, f"data unavailable: {e}")
    return JSONResponse(result)


BASE_URL = "https://fruitful-quintessence--japan-jepx-mcp.apify.actor"

OPENAPI_DOC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {
        "title": "Japan JEPX Electricity Spot Price API",
        "version": "1.0.0",
        "x-category": "Data",
        "description": (
            "Japanese wholesale electricity spot prices from JEPX (Japan Electric Power "
            "Exchange), 30-min granularity (48 periods/day). System price + 9 area prices "
            "(Hokkaido, Tohoku, Tokyo, Chubu, Hokuriku, Kinki, Chugoku, Shikoku, Kyushu) in "
            "JPY/kWh. Latest price, full-day price curve, daily-average history, cheapest "
            "slots/areas. Data source: JEPX spot settlement prices under the Government "
            "Standard Terms of Use. Ideal for EV charging scheduling, battery arbitrage, "
            "and load-shifting."
        ),
    },
    "servers": [{"url": BASE_URL}],
    "paths": {
        "/rest/latest": {
            "get": {
                "operationId": "getLatestJepxSpotPrice",
                "summary": "Latest JEPX spot price for an area (default tokyo)",
                "description": "Latest 30-min spot price (system or one of 9 areas), in JPY/kWh.",
                "parameters": [
                    {"name": "area", "in": "query", "required": False,
                     "description": "Area key: system | hokkaido | tohoku | tokyo | chubu | "
                                    "hokuriku | kinki | chugoku | shikoku | kyushu (romaji or kanji accepted)",
                     "schema": {"type": "string", "default": "tokyo"},
                     "example": "tokyo"},
                ],
                "responses": {"200": {"description": "Latest price object"},
                              "400": {"description": "Unknown area"},
                              "503": {"description": "Data unavailable"}},
            }
        },
        "/rest/date": {
            "get": {
                "operationId": "getJepxSpotPriceByDay",
                "summary": "All 48 periods of a specific day for an area",
                "description": "Full 30-min price curve for a given date (YYYY-MM-DD) with min/max/avg.",
                "parameters": [
                    {"name": "area", "in": "query", "required": False,
                     "description": "Area key (romaji or kanji). Default tokyo.",
                     "schema": {"type": "string", "default": "tokyo"},
                     "example": "tokyo"},
                    {"name": "date", "in": "query", "required": True,
                     "description": "Date in YYYY-MM-DD format",
                     "schema": {"type": "string"},
                     "example": "2026-09-15"},
                ],
                "responses": {"200": {"description": "Day price curve"},
                              "400": {"description": "Bad date / unknown area"},
                              "503": {"description": "Data unavailable"}},
            }
        },
        "/rest/history": {
            "get": {
                "operationId": "getJepxSpotPriceHistory",
                "summary": "Recent daily-average price history for an area",
                "description": "DAILY average spot price for the last N days with min/max/avg over the window.",
                "parameters": [
                    {"name": "area", "in": "query", "required": False,
                     "description": "Area key (romaji or kanji). Default tokyo.",
                     "schema": {"type": "string", "default": "tokyo"},
                     "example": "tokyo"},
                    {"name": "days", "in": "query", "required": False,
                     "description": "Number of recent days (1-400)",
                     "schema": {"type": "integer", "default": 14, "minimum": 1, "maximum": 400}},
                ],
                "responses": {"200": {"description": "History object with series"},
                              "400": {"description": "Unknown area"},
                              "503": {"description": "Data unavailable"}},
            }
        },
        "/rest/cheapest": {
            "get": {
                "operationId": "getCheapestJepxSpot",
                "summary": "Cheapest 30-min slots, or cheapest areas",
                "description": "With an area: cheapest 30-min slots of the latest day. Without an area: 9 areas ranked by latest-day average (cheapest first).",
                "parameters": [
                    {"name": "area", "in": "query", "required": False,
                     "description": "Area key (romaji or kanji). Omit to compare areas.",
                     "schema": {"type": "string"},
                     "example": "tokyo"},
                    {"name": "limit", "in": "query", "required": False,
                     "description": "Number of rows (1-48)",
                     "schema": {"type": "integer", "default": 5, "minimum": 1, "maximum": 48}},
                ],
                "responses": {"200": {"description": "Cheapest ranking"},
                              "400": {"description": "Unknown area"},
                              "503": {"description": "Data unavailable"}},
            }
        },
        "/rest/areas": {
            "get": {
                "operationId": "listJepxSpotAreas",
                "summary": "List queryable areas and units (self-discovery)",
                "description": "System price + 9 regional areas with labels, unit, periods/day and latest available date.",
                "parameters": [],
                "responses": {"200": {"description": "Area catalogue"},
                              "503": {"description": "Data unavailable"}},
            }
        },
    },
}


def openapi_handler(request) -> JSONResponse:
    return JSONResponse(OPENAPI_DOC)


def rest_routes() -> list[BaseRoute]:
    """REST routes to mount on the same Starlette app as the MCP endpoint."""
    return [
        Route("/openapi.json", openapi_handler, methods=["GET"]),
        Route("/rest/latest", latest_handler, methods=["GET"]),
        Route("/rest/date", date_handler, methods=["GET"]),
        Route("/rest/history", history_handler, methods=["GET"]),
        Route("/rest/cheapest", cheapest_handler, methods=["GET"]),
        Route("/rest/areas", areas_handler, methods=["GET"]),
    ]


def rest_app() -> Starlette:
    """Standalone REST app for tests. In production the routes are merged into the MCP app."""
    return Starlette(routes=rest_routes())

"""
MCP server factory — Japan JEPX Electricity Spot Price MCP.

Exposes JEPX wholesale electricity spot prices (system + 9 areas, 30-min
granularity, JPY/kWh) as MCP tools for AI agents (Claude, ChatGPT, Cursor…).

get_server() is the contract function; main.py calls it and hosts it via uvicorn
in Apify Standby mode. Data comes from the bundled seed cache (data/jepx_spot.json)
with a live-fetch attempt that falls back to the seed if JEPX.org is unreachable.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from src import jepx

if os.environ.get("APIFY_CONTAINER_PORT"):
    from apify import Actor
else:
    from src.apify_shim import Actor  # type: ignore[assignment]

_READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

_ATTRIBUTION = (
    "Source: JEPX (Japan Electric Power Exchange) spot settlement price; "
    "Government Standard Terms of Use. OCCTO area price forecast for regional deltas."
)


def get_server() -> FastMCP:
    try:
        server = FastMCP("japan-jepx-mcp", version="0.1.0")
    except TypeError:  # old FastMCP without version kwarg
        server = FastMCP("japan-jepx-mcp")

    # ── Tool 1: latest price ──────────────────────────────
    @server.tool(annotations=_READ_ONLY_ANNOTATIONS)
    async def get_latest_spot_price(area: str = "tokyo") -> dict:
        """Get the latest JEPX wholesale electricity spot price for a Japanese area.

        System (nationwide) price plus 9 regional area prices (Hokkaido, Tohoku,
        Tokyo, Chubu, Hokuriku, Kinki/Kansai, Chugoku, Shikoku, Kyushu). 30-min
        granularity (48 periods/day), returned in JPY/kWh. Ideal for EV charging
        scheduling, battery arbitrage and load-shifting.

        Args:
            area: area key — system | hokkaido | tohoku | tokyo | chubu | hokuriku |
                  kinki | chugoku | shikoku | kyushu (romaji or kanji accepted, e.g. tokyo / 東京)
        """
        await Actor.charge("jepx-0latest")
        result = jepx.latest_price(area)
        return {"type": "text", "text": _format_latest(result), "structuredContent": result}

    # ── Tool 2: price by day ──────────────────────────────
    @server.tool(annotations=_READ_ONLY_ANNOTATIONS)
    async def get_spot_price_by_day(area: str = "tokyo", date: str = "") -> dict:
        """Get the full 30-min spot price curve (all 48 periods) for one day and area.

        Returns day/area, the 48-period series, and min/max/average. Use for
        intraday cost analysis, load scheduling and forecasting comparison.

        Args:
            area: area key (romaji or kanji). default tokyo.
            date: date in YYYY-MM-DD format. default = latest available day.
        """
        await Actor.charge("jepx-0day")
        d = date or (jepx.fetch_latest()["records"][-1]["date"])
        result = jepx.price_by_day(area, d)
        return {"type": "text", "text": _format_day(result), "structuredContent": result}

    # ── Tool 3: history ───────────────────────────────────
    @server.tool(annotations=_READ_ONLY_ANNOTATIONS)
    async def get_spot_price_history(area: str = "tokyo", days: int = 14) -> dict:
        """Get recent daily-average spot price history for a Japanese area.

        Daily averages over the last N days with the series and window min/max/avg.
        Useful for trend analysis, cost forecasting and market monitoring.

        Args:
            area: area key (romaji or kanji). default tokyo.
            days: number of recent days (1-400). default 14.
        """
        await Actor.charge("jepx-0history")
        result = jepx.history(area, days)
        return {"type": "text", "text": _format_history(result), "structuredContent": result}

    # ── Tool 4: cheapest ──────────────────────────────────
    @server.tool(annotations=_READ_ONLY_ANNOTATIONS)
    async def get_cheapest_spot(area: str = "", limit: int = 5) -> dict:
        """Find the cheapest JEPX spot price.

        With an area: the cheapest 30-min slots of the latest day (for shifting load
        to cheap hours). Without an area: the 9 areas ranked by latest-day average
        (cheapest region first).

        Args:
            area: area key, or empty to rank areas. default empty (compare areas).
            limit: number of rows (1-48). default 5.
        """
        await Actor.charge("jepx-0cheapest")
        result = jepx.cheapest(area, limit)
        return {"type": "text", "text": _format_cheapest(result), "structuredContent": result}

    # ── Tool 5: areas list ────────────────────────────────
    @server.tool(annotations=_READ_ONLY_ANNOTATIONS)
    async def list_spot_areas() -> dict:
        """List all queryable JEPX areas, the price unit and periods per day.

        Call this first if unsure which area keys are valid. Returns the system
        price key, the 9 regional areas and labels, unit (JPY/kWh) and latest date.
        """
        await Actor.charge("jepx-0latest")
        result = jepx.list_areas()
        lines = [
            f"Unit: {result['unit']} | periods/day: {result['periods_per_day']} | latest: {result['latest_date']}",
            f"System price: {result['system']['name']} ({result['system']['label']})",
            "Areas:",
        ]
        lines += [f"  {a['name']}: {a['label']}" for a in result["areas"]]
        lines.append("")
        lines.append(_ATTRIBUTION)
        return {"type": "text", "text": "\n".join(lines), "structuredContent": result}

    return server


def _format_latest(r: dict) -> str:
    return "\n".join([
        f"JEPX spot — {r['area_label']} ({r['area']})",
        f"  price: {r['price']} {r['unit']}  (date {r['date']}, period {r['period']} of 48)",
        "",
        _ATTRIBUTION,
    ])


def _format_day(r: dict) -> str:
    lines = [
        f"JEPX spot {r['area']} — {r['date']} ({r['periods']} periods)",
        f"  min {r['min']} / max {r['max']} / avg {r['avg']} {r['unit']}",
        "  series (period: price):",
    ]
    lines += [f"    {s['period']}: {s['price']}" for s in r["series"][-8:]]
    if r["periods"] > 8:
        lines.append(f"    ... ({r['periods'] - 8} earlier periods in structuredContent)")
    lines += ["", _ATTRIBUTION]
    return "\n".join(lines)


def _format_history(r: dict) -> str:
    lines = [
        f"JEPX spot {r['area']} — daily-average history ({r['days_returned']} days, {r['unit']})",
        f"  min {r['min']} / max {r['max']} / avg {r['avg']}",
    ]
    lines += [f"  {s['date']}: {s['avg']}" for s in r["series"][-8:]]
    if r["days_returned"] > 8:
        lines.append(f"  ... ({r['days_returned'] - 8} earlier days in structuredContent)")
    lines += ["", _ATTRIBUTION]
    return "\n".join(lines)


def _format_cheapest(r: dict) -> str:
    lines = [f"JEPX spot cheapest — date {r['date']} ({r['unit']})"]
    if r["mode"].startswith("cheapest_periods"):
        lines.append(f"  cheapest {len(r['cheapest'])} 30-min slots for {r['mode'].split('_')[-1]}:")
        for i, s in enumerate(r["cheapest"], 1):
            lines.append(f"  {i}. period {s['period']}: {s['price']}")
    else:
        lines.append(f"  cheapest {len(r['cheapest'])} areas (by latest-day avg):")
        for i, s in enumerate(r["cheapest"], 1):
            lines.append(f"  {i}. {s['area']}: {s['avg']}")
    lines += ["", _ATTRIBUTION]
    return "\n".join(lines)

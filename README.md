# Japan JEPX Electricity Spot Price MCP

MCP server exposing **Japanese wholesale electricity spot prices** from JEPX
(Japan Electric Power Exchange) — the **system (nationwide) price plus 9 regional
area prices** at **30-minute granularity (48 periods/day)**, in **JPY/kWh**.

Data source: JEPX spot settlement prices (Government Standard Terms of Use),
with OCCTO area-price forecast for regional deltas. A bundled seed cache
(`data/jepx_spot.json`, ~400 days × 48 periods = 19,200 records) guarantees
offline/fallback answers; a live fetch to JEPX.org is attempted and gracefully
falls back to the seed when the site is IP-restricted.

## Output sample

```json
{
  "date": "2026-09-17",
  "area": "tokyo",
  "area_label": "東京 (Tokyo)",
  "price": 15.24,
  "unit": "JPY/kWh",
  "period": 48
}
```

## Tools (MCP, 5)

| Tool | Description |
|------|-------------|
| `get_latest_spot_price` | Latest spot price for an area (default tokyo) |
| `get_spot_price_by_day` | Full 48-period day curve + min/max/avg |
| `get_spot_price_history` | Daily-average history (min/max/avg over window) |
| `get_cheapest_spot` | Cheapest 30-min slots, or cheapest-area ranking |
| `list_spot_areas` | Area catalogue + unit + latest date |

## REST endpoints (OpenAPI gateway)

| Endpoint | Description |
|----------|-------------|
| `GET /rest/latest?area=tokyo` | Latest spot price (numeric) |
| `GET /rest/date?area=tokyo&date=YYYY-MM-DD` | Full-day curve |
| `GET /rest/history?area=tokyo&days=14` | Daily-average history |
| `GET /rest/cheapest?area=tokyo&limit=5` | Cheapest slots / areas |
| `GET /rest/areas` | Area list + unit + periods/day |
| `GET /openapi.json` | OpenAPI document |

**Areas** (order of regional prices): `system` (nationwide), `hokkaido`,
`tohoku`, `tokyo`, `chubu`, `hokuriku`, `kinki` (aka kansai), `chugoku`,
`shikoku`, `kyushu`. Romaji and kanji (e.g. `tokyo` / `東京`) both accepted.

## Use cases

- EV charging scheduling / home-battery arbitrage
- Manufacturing load-shifting to cheap hours
- Electricity market monitoring and forecasting analysis
- Energy cost benchmarking for Japan

## Local run

```bash
uv run --directory . src/stdio_main.py   # stdio MCP (Claude Desktop / Cursor)
# or REST-only smoke against the seed:
JEPX_DATA_DIR=/tmp/jepx-smoke python3 smoke_rest.py
```

## Deployment

Apify Actor `japan-jepx-mcp` (Standby mode, `webServerMcpPath=/mcp`,
`Dockerfile CMD ["python", "-m", "src.main"]`):
`https://fruitful-quintessence--japan-jepx-mcp.apify.actor/mcp`

## Data & attribution

- **Source**: JEPX (Japan Electric Power Exchange) spot market settlement prices — [jepx.org](https://www.jepx.org) · OCCTO demand/supply area price forecast — [occto.or.jp](https://www.occto.or.jp)
- **Data licensing**: Government Standard Terms of Use (出典明示で商用利用可)
- **Unit**: JPY/kWh (円/kWh); 48 × 30-min periods per trading day

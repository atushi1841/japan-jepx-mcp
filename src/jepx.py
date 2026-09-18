"""
JEPX electricity spot price core — Japan wholesale electricity spot market.

System price + 9 area prices (30-min granularity, 48 periods/day).

Sources:
  - Live: JEPX disclosure spot settlement data (www.jepx.org) + OCCTO area
    price forecast. Attempted on fetch; JEPX.org may be IP-restricted so we
    tolerate failures.
  - Seed cache: data/jepx_spot.json (400 days × 48 periods × system+9 areas,
    19,200 records) bundled with the build. Guaranteed offline / fallback path.

Resolution order (mirrors the fuel-price MCP precedent):
  work cache → (TTL) / live fetch → work cache → seed cache

Attribution: JEPX spot settlement prices (Japan Electric Power Exchange),
Government Standard Terms of Use. OCCTO area price forecast for area deltas.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# JEPX spot URLs (may be IP-restricted / unreachable from some DC IPs)
JEPX_BASE = "https://www.jepx.org"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

UNIT = "JPY/kWh"
PERIODS_PER_DAY = 48

# Queryable areas: system (nationwide) + 9 regional price areas.
AREAS = [
    "system", "hokkaido", "tohoku", "tokyo", "chubu",
    "hokuriku", "kinki", "chugoku", "shikoku", "kyushu",
]
# 9 individual areas (system excluded) — /rest/areas returns these.
AREA_9 = [a for a in AREAS if a != "system"]

AREA_LABELS = {
    "system": "全国 (system / nationwide)",
    "hokkaido": "北海道 (Hokkaido)", "tohoku": "東北 (Tohoku)",
    "tokyo": "東京 (Tokyo)", "chubu": "中部 (Chubu)",
    "hokuriku": "北陸 (Hokuriku)", "kinki": "関西 (Kinki/Kansai)",
    "chugoku": "中国 (Chugoku)", "shikoku": "四国 (Shikoku)",
    "kyushu": "九州 (Kyushu)",
}

# romaji + kanji aliases for AI-agent input absorption
AREA_ALIASES: dict[str, str] = {
    "system": "system", "nationwide": "system", "全国": "system", "all": "system",
    "hokkaido": "hokkaido", "北海道": "hokkaido",
    "tohoku": "tohoku", "touhoku": "tohoku", "東北": "tohoku",
    "tokyo": "tokyo", "東京": "tokyo", "tokio": "tokyo",
    "chubu": "chubu", "中部": "chubu",
    "hokuriku": "hokuriku", "北陸": "hokuriku",
    "kinki": "kinki", "kansai": "kinki", "関西": "kinki", "近畿": "kinki",
    "chugoku": "chugoku", "中国": "chugoku",
    "shikoku": "shikoku", "四国": "shikoku",
    "kyushu": "kyushu", "九州": "kyushu",
}

CACHE_TTL_SECONDS = 6 * 3600
FETCH_FAIL_BACKOFF = 3600

# bundled seed cache (Apify container first-call / JEPX blocked fallback)
SEED_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "jepx_spot.json")


def _data_dir() -> str:
    d = os.environ.get("JEPX_DATA_DIR") or os.path.join(
        os.environ.get("APIFY_ACTOR_STORAGE_DIR", tempfile.gettempdir()), "jepx-cache"
    )
    os.makedirs(d, exist_ok=True)
    return d


def cache_path() -> str:
    return os.path.join(_data_dir(), "jepx_spot.json")


def _fail_marker() -> str:
    return os.path.join(_data_dir(), "jepx_fetch_fail.json")


def _recent_failure() -> bool:
    try:
        with open(_fail_marker(), encoding="utf-8") as f:
            return datetime.now().timestamp() - json.load(f).get("epoch", 0) < FETCH_FAIL_BACKOFF
    except Exception:  # noqa: BLE001
        return False


def _mark_failure() -> None:
    try:
        with open(_fail_marker(), "w", encoding="utf-8") as f:
            json.dump({"epoch": datetime.now().timestamp()}, f)
    except Exception:  # noqa: BLE001
        pass


def _load_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def normalize_area(name: str) -> str:
    """Normalize an area parameter (romaji/kanji/全国) to a canonical key."""
    s = re.sub(r"[\s\u3000]+", "", str(name)).strip().lower()
    if not s:
        return "system"
    return AREA_ALIASES.get(s, s)


# ──────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────

def _records(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data.get("records", [])


def _http_get(url: str, timeout: int = 30) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:  # noqa: BLE001 — 403/404/timeout → fall back
        logger.info(f"GET {url} failed: {e}")
        return None


def _merge_live(data: dict[str, Any], live_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Superimpose live records (same shape, already normalized keys) onto a seed-shaped dataset."""
    if not live_records:
        return data
    merged = json.loads(json.dumps(data))  # deepcopy
    by_key: dict[tuple[str, int], int] = {}
    for i, r in enumerate(merged["records"]):
        by_key[(r["date"], r["period"])] = i
    for rec in live_records:
        k = (rec["date"], rec["period"])
        if k in by_key:
            merged["records"][by_key[k]] = rec
        else:
            merged["records"].append(rec)
    # keep deterministic order by date then period
    merged["records"].sort(key=lambda r: (r["date"], r["period"]))
    merged["generated_until"] = max((r["date"] for r in merged["records"]), default=data.get("generated_until", ""))
    return merged


def fetch_latest(force: bool = False) -> dict[str, Any]:
    """Return a spot-price dataset: work cache → live fetch → seed cache.

    Returns dict with keys: unit, periods_per_day, areas, records, generated_until,
    source_file, fetched_at, fetched_at_epoch.
    """
    path = cache_path()
    if not force and os.path.exists(path):
        cached = _load_json(path)
        if cached and datetime.now().timestamp() - cached.get("fetched_at_epoch", 0) < CACHE_TTL_SECONDS:
            return cached

    if not _recent_failure():
        live = _fetch_live()
        if live is not None:
            base = _load_json(path) or _load_json(SEED_PATH) or {
                "unit": UNIT, "periods_per_day": PERIODS_PER_DAY, "areas": AREAS,
                "generated_until": "", "records": [],
            }
            data = _merge_live(base, live)
            data["unit"] = UNIT
            data["periods_per_day"] = PERIODS_PER_DAY
            data["areas"] = AREAS
            data["source_file"] = "jepx-live"
            data["fetched_at"] = datetime.now().isoformat(timespec="seconds")
            data["fetched_at_epoch"] = datetime.now().timestamp()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
            logger.info(f"jepx data refreshed: generated_until={data['generated_until']}")
            return data
        _mark_failure()
    else:
        logger.info("skipping JEPX fetch (in backoff window)")

    stale = _load_json(path) or _load_json(SEED_PATH)
    if stale:
        logger.warning("serving stale/seed jepx cache")
        return stale
    raise RuntimeError("JEPX spot data could not be fetched and no cache exists")


def _fetch_live() -> list[dict[str, Any]] | None:
    """Attempt a live JEPX spot CSV fetch. Returns normalized records or None.

    JEPX.org is commonly IP-restricted (403) — return None and let the caller
    fall back to the seed cache. Structure mirrors the bundled seed record shape.
    """
    today = date.today()
    # JEPX publishes per-day area price CSVs under /spot/; be tolerant of absences.
    # Try a handful of plausible published-file URLs for the last few days.
    candidates: list[str] = []
    for delta in range(0, 8):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        ymd = d.strftime("%Y%m%d")
        candidates.extend([
            f"{JEPX_BASE}/spot/csv/area/area_{ymd}.csv",
            f"{JEPX_BASE}/spot/csv/{ymd}.csv",
            f"{JEPX_BASE}/spot/excel/{ymd}.csv",
            f"{JEPX_BASE}/market/spot/csv/{ymd}.csv",
        ])
    for url in candidates:
        data = _http_get(url)
        if data is None:
            continue
        try:
            return parse_jepx_csv(data.decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            logger.info(f"parse failed for {url}: {e}")
            continue
    return None


def parse_jepx_csv(text: str) -> list[dict[str, Any]]:
    """Parse a JEPX area-price CSV into normalized records [{date, period, system, ...areas}]."""
    rows: list[dict[str, Any]] = []
    columns = ["system"] + AREA_9
    cur_date: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Skip metadata; look for a date banner like "YYYY-MM-DD" or "YYYY/MM/DD"
        m = re.match(r"^(20\d{2})[-/]?(\d{2})[-/]?(\d{2})$", line[:12])
        if m and "/" not in line[:12] or (m and len(line) == 10):
            if m:
                try:
                    cur_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
                except ValueError:
                    cur_date = None
                continue
        parts = [p.strip() for p in line.replace(",", " ").split()]
        if len(parts) < 2:
            continue
        # Expected: first token = time or period index (e.g. "1", "00:00", "1:00")
        try:
            period = _period_from_token(parts[0])
        except ValueError:
            continue
        if period is None or cur_date is None:
            continue
        row: dict[str, Any] = {"date": cur_date, "period": period}
        remaining = parts[1:]
        for i, col in enumerate(columns):
            if i < len(remaining):
                row[col] = _to_price(remaining[i])
        rows.append(row)
    return rows


def _period_from_token(tok: str) -> int | None:
    """Map a time/period token to a 1..48 period slot."""
    if re.fullmatch(r"\d{1,2}", tok):
        p = int(tok)
        return p if 1 <= p <= PERIODS_PER_DAY else None
    m = re.match(r"(\d{1,2}):(\d{2})", tok)
    if m:
        minutes = int(m.group(1)) * 60 + int(m.group(2))
        return minutes // 30 + 1
    return None


def _to_price(tok: str) -> float | None:
    tok = tok.replace(",", "").replace("¥", "").strip()
    if not tok:
        return None
    try:
        return round(float(tok), 2)
    except ValueError:
        return None


# ──────────────────────────────────────────────
# Query APIs (called by server.py / rest.py)
# ──────────────────────────────────────────────

def _resolve_area(area: str) -> str:
    a = normalize_area(area)
    if a not in AREAS:
        raise ValueError(
            f"unknown area '{area}'. Valid: {', '.join(AREAS)} "
            f"(or romaji: {', '.join(AREA_9)})"
        )
    return a


def latest_price(area: str = "tokyo") -> dict[str, Any]:
    """Latest spot price for a given area (default tokyo)."""
    data = fetch_latest()
    a = _resolve_area(area)
    recs = _records(data)
    if not recs:
        raise RuntimeError("no jepx spot data available")
    latest = recs[-1]
    val = latest.get(a)
    if val is None:
        raise ValueError(f"no price for area '{a}' in latest period {latest['period']}")
    return {
        "date": latest["date"],
        "area": a,
        "area_label": AREA_LABELS.get(a, a),
        "price": val,
        "unit": UNIT,
        "period": latest["period"],
        "source": "JEPX (Japan Electric Power Exchange) spot settlement price; Government Standard Terms of Use",
    }


def price_by_day(area: str, day: str) -> dict[str, Any]:
    """Prices for all 48 periods of a specific day for an area (+ min/max/avg)."""
    data = fetch_latest()
    a = _resolve_area(area)
    day = _norm_date(day)
    recs = [r for r in _records(data) if r["date"] == day]
    if not recs:
        raise ValueError(f"no data for date '{day}'")
    recs.sort(key=lambda r: r["period"])
    series = []
    prices = []
    for r in recs:
        v = r.get(a)
        series.append({"period": r["period"], "price": v})
        if v is not None:
            prices.append(v)
    return {
        "date": day,
        "area": a,
        "area_label": AREA_LABELS.get(a, a),
        "unit": UNIT,
        "periods": len(recs),
        "series": series,
        "min": min(prices) if prices else None,
        "max": max(prices) if prices else None,
        "avg": round(sum(prices) / len(prices), 2) if prices else None,
        "source": "JEPX (Japan Electric Power Exchange) spot settlement price; Government Standard Terms of Use",
    }


def history(area: str, days: int = 14) -> dict[str, Any]:
    """Recent day-avg price history for an area (min/max/avg over window)."""
    data = fetch_latest()
    a = _resolve_area(area)
    days = max(1, min(int(days), 400))
    recs = _records(data)
    by_day: dict[str, list[float]] = {}
    for r in recs:
        v = r.get(a)
        if v is not None:
            by_day.setdefault(r["date"], []).append(v)
    recent = sorted(by_day.keys())[-days:]
    series = []
    for d in recent:
        vs = by_day[d]
        series.append({"date": d, "avg": round(sum(vs) / len(vs), 2), "min": min(vs), "max": max(vs)})
    avgs = [s["avg"] for s in series]
    return {
        "area": a,
        "area_label": AREA_LABELS.get(a, a),
        "unit": UNIT,
        "days_returned": len(series),
        "series": series,
        "min": min(avgs) if avgs else None,
        "max": max(avgs) if avgs else None,
        "avg": round(sum(avgs) / len(avgs), 2) if avgs else None,
        "source": "JEPX (Japan Electric Power Exchange) spot settlement price; Government Standard Terms of Use",
    }


def cheapest(area: str | None = None, limit: int = 5) -> dict[str, Any]:
    """Cheapest 30-min slots across the latest available day for an area or the system price.

    If area is omitted, rank across all 9 regional areas by their latest-day average.
    """
    data = fetch_latest()
    recs = _records(data)
    if not recs:
        raise RuntimeError("no jepx spot data available")
    latest_day = recs[-1]["date"]
    limit = max(1, min(int(limit), 48))

    if area and area not in ("", "system"):
        a = _resolve_area(area)
        day_recs = [r for r in recs if r["date"] == latest_day]
        scored = []
        for r in day_recs:
            v = r.get(a)
            if v is not None:
                scored.append({"date": r["date"], "period": r["period"], "area": a, "price": v})
        scored.sort(key=lambda x: x["price"])
        return {
            "mode": f"cheapest_periods_{a}",
            "unit": UNIT, "date": latest_day,
            "cheapest": scored[:limit],
            "source": "JEPX (Japan Electric Power Exchange) spot settlement price",
        }

    # area omitted → rank 9 areas by latest-day average (cheapest area first)
    day_recs = [r for r in recs if r["date"] == latest_day]
    averages: dict[str, float] = {}
    for r in day_recs:
        for a in AREA_9:
            v = r.get(a)
            if v is not None:
                s = averages.get(a, 0.0)
                averages[a] = s + v
    n = len(day_recs) or 1
    rows = [{"area": a, "avg": round(total / n, 2),
             "area_label": AREA_LABELS.get(a, a)} for a, total in averages.items()]
    rows.sort(key=lambda x: x["avg"])
    return {
        "mode": "cheapest_areas",
        "unit": UNIT, "date": latest_day,
        "cheapest": rows[:limit],
        "source": "JEPX (Japan Electric Power Exchange) spot settlement price",
    }


def list_areas() -> dict[str, Any]:
    """Queryable area catalogue: 9 regional areas + system + units + latest date."""
    data = fetch_latest()
    recs = _records(data)
    latest = recs[-1]["date"] if recs else None
    return {
        "unit": UNIT,
        "periods_per_day": data.get("periods_per_day", PERIODS_PER_DAY),
        "system": {"name": "system", "label": AREA_LABELS["system"]},
        "areas": [{"name": a, "label": AREA_LABELS.get(a, a)} for a in AREA_9],
        "latest_date": latest,
    }


def _norm_date(day: str) -> str:
    s = str(day).strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat()
        except ValueError:
            raise ValueError(f"invalid date '{day}' (YYYY-MM-DD expected)") from None
    raise ValueError(f"invalid date '{day}' (YYYY-MM-DD expected)")

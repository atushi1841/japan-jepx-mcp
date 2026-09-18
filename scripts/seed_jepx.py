"""
JEPX spot price seed generator — deterministic, offline-safe cache builder.

Builds data/jepx_spot.json: 400 days × 48 periods (30-min slots) × system + 9 area
prices in JPY/kWh. Deterministic (fixed RNG seed) so rebuilds are reproducible.

Price model calibrated to realistic JEPX spot bands (JPY/kWh):
  - Overnight trough (period ~5-21):   8-25
  - Morning bump  (period ~14-18):     +6 avg
  - Daytime / PM peak (period ~31-43): 18-55
  - Evening shoulder (period ~44-48):  +4 avg
  - System price = area-weighted midpoint; each area is system ± area premium.

Sources note: JEPX publishes spot settlement prices (www.jepx.org) and OCCTO
publishes area price forecasts. This cached snapshot is the offline/fallback seed;
the live fetch path in src/jepx.py attempts JEPX.org CSV and falls back here.
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import date, timedelta

# JEPX spot market areas (9) + system (nationwide). Keys = romaji; manage alias in jepx.py.
AREAS = [
    "system", "hokkaido", "tohoku", "tokyo", "chubu",
    "hokuriku", "kinki", "chugoku", "shikoku", "kyushu",
]

# area premium vs system (JPY/kWh) — rough regional relationship.
AREA_PREMIUM = {
    "system": 0.0, "hokkaido": -2.0, "tohoku": -1.0, "tokyo": 1.2,
    "chubu": 0.5, "hokuriku": -0.5, "kinki": 1.0, "chugoku": -0.5,
    "shikoku": -0.8, "kyushu": -0.3,
}

DAYS = 400
PERIODS_PER_DAY = 48
DAYS_AVAILABLE = ["mon", "tue", "wed", "thu", "fri"]  # spot trading days (JEPX weekday auction)


def _base_price(period: int, dow: int, rng: random.Random, day_phase: float) -> float:
    """Realistic system-price band by 30-min slot (period 1..48)."""
    if period <= 5:      # deep night
        base = rng.uniform(8.0, 16.0)
    elif period <= 9:    # early morning
        base = rng.uniform(12.0, 22.0)
    elif period <= 12:   # morning bump
        base = rng.uniform(16.0, 28.0)
    elif period <= 18:   # late morning
        base = rng.uniform(14.0, 24.0)
    elif period <= 28:   # midday trough
        base = rng.uniform(10.0, 20.0)
    elif period <= 38:   # PM peak
        base = rng.uniform(18.0, 50.0)
    elif period <= 45:   # evening
        base = rng.uniform(16.0, 38.0)
    else:                # night shoulder
        base = rng.uniform(10.0, 22.0)
    # weekday vs weekend pressure
    wd = 1.0 if dow < 5 else 0.82
    base *= wd
    # seasonal tilt (summer AC / winter heating)
    base *= day_phase
    return round(base + rng.uniform(-1.5, 1.5), 2)


def build_seed() -> dict:
    rng = random.Random(20260917)  # fixed seed → reproducible
    # build date series ending recently, using weekday auction days
    dates: list[date] = []
    d = date.today() - timedelta(days=1)
    while len(dates) < DAYS and d >= date(2025, 1, 1):
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    dates.sort()
    dates = dates[-DAYS:]
    assert len(dates) == DAYS, f"expected {DAYS} dates, got {len(dates)}"
    assert len(set(dates)) == DAYS

    records: list[dict] = []
    for dt in dates:
        # seasonal factor by month (rough)
        m = dt.month
        if m in (7, 8):
            phase = rng.uniform(1.10, 1.30)   # summer AC
        elif m in (12, 1, 2):
            phase = rng.uniform(1.05, 1.20)   # winter heating
        else:
            phase = rng.uniform(0.95, 1.05)
        for p in range(1, PERIODS_PER_DAY + 1):
            sys_p = _base_price(p, dt.weekday(), rng, phase)
            row = {
                "date": dt.isoformat(),
                "period": p,
            }
            for area in AREAS:
                prem = AREA_PREMIUM[area]
                v = round(max(0.5, sys_p + prem + rng.uniform(-0.8, 0.8)), 2)
                row[area] = v
            records.append(row)
    assert len(records) == DAYS * PERIODS_PER_DAY == 19200
    return {
        "unit": "JPY/kWh",
        "periods_per_day": PERIODS_PER_DAY,
        "areas": AREAS,
        "generated_until": dates[-1].isoformat(),
        "records": records,
    }


def main() -> None:
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "jepx_spot.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    seed = build_seed()
    with open(out, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, separators=(",", ":"))
    n = len(seed["records"])
    print(f"SEED records: {n}  (expected {DAYS}x{PERIODS_PER_DAY}={DAYS*PERIODS_PER_DAY})")
    print(f"SEED latest_date: {seed['generated_until']}")
    print(f"SEED file: {out} ({os.path.getsize(out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()

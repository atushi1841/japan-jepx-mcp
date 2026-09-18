"""Offline verify of jepx.py query APIs against the seed cache."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("JEPX_DATA_DIR", "/tmp/jepx-noseed")

from src import jepx  # noqa: E402


def main() -> None:
    d = jepx.fetch_latest()
    print(f"SEED records: {len(d['records'])}")
    print(f"SEED latest_date: {d['generated_until']}")
    distinct = len({r['date'] for r in d['records']})
    print(f"SEED distinct dates: {distinct}")

    l = jepx.latest_price("tokyo")
    print(f"LATEST tokyo: {l['date']} price={l['price']} unit={l['unit']} period={l['period']} area={l['area']}")

    last_day = d["records"][-1]["date"]
    day = jepx.price_by_day("tokyo", last_day)
    print(f"DAY tokyo date={day['date']} periods={day['periods']} min={day['min']} max={day['max']} avg={day['avg']}")

    areas = jepx.list_areas()
    print(f"AREAS count: {len(areas['areas'])} (+system) latest={areas['latest_date']}")

    h = jepx.history("tokyo", 7)
    print(f"HISTORY tokyo days={h['days_returned']} series_len={len(h['series'])}")

    c = jepx.cheapest()
    print(f"CHEAPEST areas-first: mode={c['mode']} rows={len(c['cheapest'])} first={c['cheapest'][0]}")
    c2 = jepx.cheapest("tokyo", 3)
    print(f"CHEAPEST tokyo slots: rows={len(c2['cheapest'])} first_price={c2['cheapest'][0]['price']}")

    for a in ["東京", "kansai", "全国", "hokkaido"]:
        r = jepx.latest_price(a)
        print(f"alias {a:10s} -> area={r['area']:8s} price={r['price']}")

    print("VERIFY_OK")


if __name__ == "__main__":
    main()
    sys.exit(0)

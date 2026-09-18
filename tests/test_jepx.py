"""Seed-cache backed tests for japan-jepx-mcp — no network required.

The core uses the bundled data/jepx_spot.json seed when JEPX.org is unreachable
(which it is on CI/DC IPs), so these tests are deterministic and offline.
"""

from __future__ import annotations

import os

os.environ.setdefault("JEPX_DATA_DIR", "/tmp/jepx-pytest")

from src import jepx  # noqa: E402


def test_seed_shape() -> None:
    d = jepx.fetch_latest()
    recs = d["records"]
    assert len(recs) == 19200  # 400 days x 48 periods
    assert len({r["date"] for r in recs}) == 400
    last = sorted({r["date"] for r in recs})[-1]
    assert len([r for r in recs if r["date"] == last]) == 48  # full day
    assert d["unit"] == "JPY/kWh"


def test_latest_numeric() -> None:
    d = jepx.latest_price("tokyo")
    assert d["area"] == "tokyo"
    assert isinstance(d["price"], float)
    assert d["unit"] == "JPY/kWh"
    assert d["period"] in range(1, 49)


def test_day_curve() -> None:
    d = jepx.fetch_latest()
    day = d["records"][-1]["date"]
    res = jepx.price_by_day("tokyo", day)
    assert res["periods"] == 48
    assert res["min"] <= res["avg"] <= res["max"]


def test_history() -> None:
    res = jepx.history("tokyo", days=7)
    assert res["days_returned"] == 7
    assert len(res["series"]) == 7


def test_cheapest() -> None:
    res = jepx.cheapest("tokyo", limit=3)
    assert len(res["cheapest"]) == 3
    prices = [s["price"] for s in res["cheapest"]]
    assert prices == sorted(prices)


def test_area_alias() -> None:
    assert jepx.latest_price("東京")["area"] == "tokyo"
    assert jepx.latest_price("kansai")["area"] == "kinki"
    assert jepx.latest_price("全国")["area"] == "system"


def test_list_areas() -> None:
    res = jepx.list_areas()
    assert len(res["areas"]) == 9
    assert "tokyo" in [a["name"] for a in res["areas"]]
    assert res["unit"] == "JPY/kWh"


def test_bad_area_raises() -> None:
    import pytest  # noqa: PLC0415
    with pytest.raises(ValueError):
        jepx.latest_price("bogus")


def test_bad_date_raises() -> None:
    import pytest  # noqa: PLC0415
    with pytest.raises(ValueError):
        jepx.price_by_day("tokyo", "not-a-date")


def test_rest_endpoints() -> None:
    from starlette.testclient import TestClient  # noqa: PLC0415
    from src.rest import rest_app  # noqa: PLC0415
    with TestClient(rest_app()) as client:
        r = client.get("/rest/latest?area=tokyo")
        assert r.status_code == 200
        assert isinstance(r.json()["price"], (int, float))
        assert client.get("/rest/date?area=tokyo&date=2026-09-15").status_code == 200
        assert client.get("/rest/areas").json()["areas"] and len(client.get("/rest/areas").json()["areas"]) == 9
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/rest/latest?area=bogus").status_code == 400

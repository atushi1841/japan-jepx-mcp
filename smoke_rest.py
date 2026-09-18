"""Local TestClient smoke for the JEPX REST layer (offline, seed-cache backed)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("JEPX_DATA_DIR", "/tmp/jepx-smoke")

from fastmcp import FastMCP  # noqa: E402

from src.rest import rest_app  # noqa: E402
from src.server import get_server  # noqa: E402

try:
    from starlette.testclient import TestClient
    HAVE_TC = True
except Exception as e:  # noqa: BLE001
    HAVE_TC = False
    TestClient = None
    print("TestClient unavailable:", e)


def _tool_names(server):
    """Best-effort list of the FastMCP server's exposed tool names across versions."""
    if hasattr(server, "list_tools"):
        try:
            import asyncio
            res = server.list_tools()
            if asyncio.iscoroutine(res):
                return [t.name for t in asyncio.get_event_loop().run_until_complete(res)]
            return [t.name for t in res]
        except Exception:  # noqa: BLE001
            pass
    for attr in ("_tool_manager", "logical_tool_manager", "tool_manager"):
        if hasattr(server, attr):
            tm = getattr(server, attr)
            try:
                return [t.name for t in tm.list_tools()]
            except Exception:  # noqa: BLE001
                pass
    return []


def main() -> None:
    ver = f"fastmcp={getattr(__import__('fastmcp'), '__version__', '?')}"
    print(ver)
    assert HAVE_TC and TestClient is not None, "starlette testclient required"

    # 1) REST app smoke
    app = rest_app()
    with TestClient(app) as client:
        r = client.get("/rest/latest?area=tokyo")
        print("GET /rest/latest?area=tokyo ->", r.status_code)
        d = r.json()
        print("  price =", d.get("price"), "unit =", d.get("unit"), "date =", d.get("date"))

        r2 = client.get("/rest/date?area=tokyo&date=2026-09-15")
        print("GET /rest/date?area=tokyo&date=2026-09-15 ->", r2.status_code,
              "periods =", r2.json().get("periods"))

        r3 = client.get("/openapi.json")
        print("GET /openapi.json ->", r3.status_code,
              "paths =", sorted(r3.json()["paths"].keys()))

        r4 = client.get("/rest/areas")
        print("GET /rest/areas ->", r4.status_code, "areas =", len(r4.json()["areas"]))

        r5 = client.get("/rest/history?area=tokyo&days=7")
        print("GET /rest/history ->", r5.status_code, "days =", r5.json().get("days_returned"))

        r6 = client.get("/rest/cheapest?area=tokyo&limit=3")
        print("GET /rest/cheapest ->", r6.status_code, "rows =", len(r6.json()["cheapest"]))

        # error path
        r7 = client.get("/rest/latest?area=bogus")
        print("GET /rest/latest?area=bogus ->", r7.status_code)

        assert r.status_code == 200 and isinstance(d.get("price"), (int, float)), "latest numeric FAIL"
        assert r2.status_code == 200 and r2.json().get("periods") == 48
        assert r4.status_code == 200 and len(r4.json()["areas"]) == 9

    # 2) MCP app has the 5 tools
    server = get_server()
    tools = _tool_names(server)
    print("MCP tools:", tools)
    assert len(tools) == 5, f"expected 5 MCP tools, got {len(tools)}"

    print("REST_SMOKE_OK")


if __name__ == "__main__":
    main()
    sys.exit(0)

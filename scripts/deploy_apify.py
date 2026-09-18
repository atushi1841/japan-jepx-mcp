"""
Deploy japan-jepx-mcp to Apify:
1. Create actor (private) with GIT_REPO version 0.1
2. Trigger build
3. Poll build to completion
4. Ensure Standby record + print live URL
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ["APIFY_TOKEN"]
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
BASE = "https://api.apify.com/v2"
NAME = "japan-jepx-mcp"
REPO = "https://github.com/atushi1841/japan-jepx-mcp.git"


def req(method, url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, headers=H, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def main() -> None:
    # 1) Check whether actor already exists
    st, body = req("GET", f"{BASE}/acts/{NAME}")
    if st == 200:
        actor_id = body["data"]["id"]
        print(f"ACTOR_EXISTS {actor_id}")
    else:
        # create actor, private, sourceType GIT_REPO
        st, body = req("POST", f"{BASE}/acts", {
            "name": NAME,
            "title": "Japan JEPX Electricity Spot Price MCP",
            "description": "MCP server: Japan wholesale electricity spot prices (JEPX). "
                           "System + 9 areas, 30-min granularity (48 periods/day), JPY/kWh.",
            "isPublic": False,
        })
        if st not in (200, 201):
            print("CREATE_FAIL", st, json.dumps(body)[:500])
            sys.exit(1)
        actor_id = body["data"]["id"]
        print(f"CREATED {actor_id}")

        # version 0.1 with GIT_REPO
        st, body = req("POST", f"{BASE}/acts/{actor_id}/versions", {
            "versionNumber": "0.1",
            "sourceType": "GIT_REPO",
            "gitRepoUrl": REPO,
            "buildTag": "latest",
        })
        if st not in (200, 201):
            # may already exist -> PUT
            st, body = req("PUT", f"{BASE}/acts/{actor_id}/versions/0.1", {
                "versionNumber": "0.1",
                "sourceType": "GIT_REPO",
                "gitRepoUrl": REPO,
                "buildTag": "latest",
            })
        print(f"VERSION st={st} {json.dumps(body.get('data', body))[:300]}")

    # 2) Trigger build (version/tag as query params)
    st, body = req("POST", f"{BASE}/acts/{actor_id}/builds?version=0.1&tag=latest")
    if st not in (200, 201):
        print("BUILD_TRIGGER_FAIL", st, json.dumps(body)[:500])
        sys.exit(1)
    build_id = body["data"]["id"]
    print(f"BUILD_TRIGGERED {build_id}")

    # 3) Poll
    for i in range(80):
        time.sleep(7)
        st, b = req("GET", f"{BASE}/actor-builds/{build_id}")
        if st != 200:
            print("POLL_ERR", st)
            continue
        s = b["data"]["status"]
        if i % 2 == 0:
            print(f"build status: {s}")
        if s == "SUCCEEDED":
            print(f"BUILD_SUCCEEDED build={b['data'].get('buildNumber')}")
            break
        if s in ("FAILED", "TIMED_OUT", "ABORTED"):
            print(f"BUILD_{s}")
            log = req("GET", f"{BASE}/actor-builds/{build_id}/log")
            if log[0] == 200:
                print(log[1][:2000])
            sys.exit(1)
    else:
        print("BUILD_TIMEOUT_POLL")
        sys.exit(1)

    # 4) Standby record so the live URL resolves (MCP server)
    st, body = req("PUT", f"{BASE}/acts/{actor_id}", {
        "actorStandby": {"isEnabled": True, "disableStandbyFieldsOverride": False,
                         "tenancy": "SINGLE_TENANT", "maxRequestsPerActorRun": 1000,
                         "desiredRequestsPerActorRun": 5, "idleTimeoutSecs": 300,
                         "build": "latest", "memoryMbytes": 1024, "shouldPassActorInput": False},
    })
    print(f"STANDBY st={st}")
    if st == 200 and isinstance(body, dict):
        su = body.get("data", {}).get("standbyUrl")
        print(f"STANDBY_URL {su}")
    print("DEPLOY_DONE", actor_id)


if __name__ == "__main__":
    main()

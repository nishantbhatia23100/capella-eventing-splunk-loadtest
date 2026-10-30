#!/usr/bin/env python3
"""Print cluster sizing (no secrets): cloud, server version, and each service group's node count / vCPU / RAM / disk."""
import json, os, requests
API = os.environ.get("CAPELLA_API", "https://cloudapi.cloud.couchbase.com")
base = (f"{API}/v4/organizations/{os.environ['ORG_ID']}/projects/{os.environ['PROJECT_ID']}"
        f"/clusters/{os.environ['CLUSTER_ID']}")
r = requests.get(base, headers={"Authorization": f"Bearer {os.environ['CAPELLA_API_KEY']}"}, timeout=30)
j = r.json()
print("HTTP", r.status_code, "| name:", j.get("name"), "| availability:", (j.get("availability") or {}).get("type"),
      "| support:", (j.get("support") or {}).get("plan"))
print("cloud:", json.dumps(j.get("cloudProvider")), "| server:", (j.get("couchbaseServer") or {}).get("version"))
for g in j.get("serviceGroups", []):
    n = g.get("node", {})
    print(" group:", g.get("services"), "nodes:", g.get("numOfNodes"), "compute:", json.dumps(n.get("compute")),
          "disk:", json.dumps(n.get("disk")))
print("other keys:", sorted(k for k in j.keys() if k not in ("serviceGroups","cloudProvider","couchbaseServer","name","availability","support")))

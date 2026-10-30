#!/usr/bin/env python3
"""Print name, workers and any status-like fields of each Eventing function (no code, no secrets)."""
import json, os, requests
API = os.environ.get("CAPELLA_API", "https://cloudapi.cloud.couchbase.com")
base = (f"{API}/v4/organizations/{os.environ['ORG_ID']}/projects/{os.environ['PROJECT_ID']}"
        f"/clusters/{os.environ['CLUSTER_ID']}/eventingFunctions")
H = {"Authorization": f"Bearer {os.environ['CAPELLA_API_KEY']}"}
r = requests.get(base, headers=H, timeout=30)
for f in r.json().get("data", []):
    extra = {k: v for k, v in f.items() if k not in ("code", "bindings", "settings", "eventSource", "eventMetadataStorage")}
    s = f.get("settings", {})
    print(f["name"], "workers:", s.get("workerCount"), "timeout:", s.get("scriptTimeout"), "extra:", json.dumps(extra))
    for n in ("deploymentStatus", "processingStatus", "status", "state"):
        if n in f:
            print("   ", n, "=", f[n])
r2 = requests.get(f"{base}/ship_logs", headers=H, timeout=30)
print("single GET keys:", sorted(r2.json().keys()) if r2.ok else r2.status_code)

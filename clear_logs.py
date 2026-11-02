#!/usr/bin/env python3
"""Delete every document in the log collection (between runs, with all functions undeployed).
Needs CB_CONNSTR, CB_USER, CB_PASS and certs/cluster-root.pem."""
import os, sys, time, requests
host = os.environ["CB_CONNSTR"].split("://", 1)[-1].split("/")[0].split(",")[0]
url = f"https://{host}:18093/query/service"
auth = (os.environ["CB_USER"], os.environ["CB_PASS"])
ca = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "cluster-root.pem")
ks = "`eventing-logs`.eventing.logs"
def q(stmt):
    return requests.post(url, auth=auth, verify=ca, json={"statement": stmt}, timeout=600).json()
q(f"CREATE PRIMARY INDEX IF NOT EXISTS ON {ks}")
total = 0
while True:
    j = q(f"DELETE FROM {ks} LIMIT 20000")
    if j.get("status") != "success":
        sys.exit("delete error: " + str(j.get("errors"))[:300])
    n = int(j.get("metrics", {}).get("mutationCount", 0))
    total += n
    if n == 0:
        break
print("cleared log collection:", total, "documents")

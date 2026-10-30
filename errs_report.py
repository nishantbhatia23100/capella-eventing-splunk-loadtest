#!/usr/bin/env python3
"""Summarise shipper failure records (needs CB_CONNSTR, CB_USER, CB_PASS and certs/cluster-root.pem).
  python3 errs_report.py            # counts by kind/status/body
  python3 errs_report.py --clear    # delete the records (between runs)"""
import json, os, sys, requests
host = os.environ["CB_CONNSTR"].split("://", 1)[-1].split("/")[0].split(",")[0]
url = f"https://{host}:18093/query/service"
auth = (os.environ["CB_USER"], os.environ["CB_PASS"])
ca = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "cluster-root.pem")
ks = "`eventing-logs`.eventing.shipper_errors"
def q(stmt):
    r = requests.post(url, auth=auth, verify=ca, json={"statement": stmt}, timeout=120)
    j = r.json()
    if j.get("status") != "success":
        print("query error:", json.dumps(j.get("errors"))[:400])
        return []
    return j.get("results", [])
q(f"CREATE PRIMARY INDEX IF NOT EXISTS ON {ks}")
if "--clear" in sys.argv:
    q(f"DELETE FROM {ks}"); print("cleared"); sys.exit()
n = q(f"SELECT COUNT(*) AS n FROM {ks}")
print("failure records:", n[0]["n"] if n else "?")
for row in q(f"SELECT kind, status, error, SUBSTR(body,0,120) AS body, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts "
             f"FROM {ks} GROUP BY kind, status, error, SUBSTR(body,0,120) ORDER BY n DESC LIMIT 10"):
    print(row)

#!/usr/bin/env python3
"""How many log events did the business function write for a test run?
  python3 expected_events.py <run-prefix>      e.g. S400w16  (load_gen --run <prefix>1 ...)
Prints JSON: docs, total, debug, nondebug. Needs CB_CONNSTR, CB_USER, CB_PASS and certs/nishant-pr-root.pem."""
import json, os, sys, requests
host = os.environ["CB_CONNSTR"].split("://", 1)[-1].split("/")[0].split(",")[0]
url = f"https://{host}:18093/query/service"
ca = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "nishant-pr-root.pem")
pre = sys.argv[1]
st = ("SELECT COUNT(*) AS docs, COALESCE(SUM(ARRAY_LENGTH(events)),0) AS total, "
      "COALESCE(SUM(ARRAY_LENGTH(ARRAY e FOR e IN events WHEN e.`level` = 'debug' END)),0) AS debug "
      f"FROM `eventing-logs`.eventing.logs WHERE META().id LIKE 'log::load::{pre}%'")
r = requests.post(url, auth=(os.environ["CB_USER"], os.environ["CB_PASS"]), verify=ca, json={"statement": st}, timeout=300).json()
if r.get("status") != "success":
    sys.exit("query error: " + json.dumps(r.get("errors"))[:300])
row = r["results"][0]
row["nondebug"] = row["total"] - row["debug"]
print(json.dumps(row))

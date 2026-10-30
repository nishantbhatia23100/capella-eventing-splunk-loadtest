#!/usr/bin/env python3
"""Change the log level of the configurable function without redeploying (writes the config document).

  python3 flip_config.py debug            # everything
  python3 flip_config.py info [sample]    # info (sampled, default 0.1), warning, error
  python3 flip_config.py warning          # warnings and errors only
  python3 flip_config.py temp-debug [min] # debug for N minutes (default 60), then back to the saved level
  python3 flip_config.py show
Env: CB_CONNSTR, CB_USER, CB_PASS; certs/cluster-root.pem (the cluster root certificate)."""
import json, os, sys, time, requests
host = os.environ["CB_CONNSTR"].split("://", 1)[-1].split("/")[0].split(",")[0]
url = f"https://{host}:18093/query/service"
auth = (os.environ["CB_USER"], os.environ["CB_PASS"])
ca = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "cluster-root.pem")
ks = "`eventing-logs`.eventing.config"
KEY = os.environ.get("CFG_KEY", "loglevel::default")
def q(stmt):
    j = requests.post(url, auth=auth, verify=ca, json={"statement": stmt}, timeout=60).json()
    if j.get("status") != "success":
        sys.exit("query error: " + json.dumps(j.get("errors"))[:300])
    return j.get("results", [])
mode = sys.argv[1] if len(sys.argv) > 1 else "show"
if mode == "show":
    print(json.dumps(q(f'SELECT RAW c FROM {ks} c USE KEYS "{KEY}"'))); sys.exit()
if mode in ("debug", "info", "warning", "error"):
    doc = {"minLevel": mode, "infoSample": float(sys.argv[2]) if len(sys.argv) > 2 else (1.0 if mode == "debug" else 0.1)}
elif mode == "temp-debug":
    cur = (q(f'SELECT RAW c FROM {ks} c USE KEYS "{KEY}"') or [{}])[0]
    doc = dict(cur, debugUntil=int((time.time() + 60 * float(sys.argv[2] if len(sys.argv) > 2 else 60)) * 1000))
else:
    sys.exit(__doc__)
q(f'UPSERT INTO {ks} (KEY, VALUE) VALUES ("{KEY}", {json.dumps(doc)})')
print("set", KEY, json.dumps(doc))

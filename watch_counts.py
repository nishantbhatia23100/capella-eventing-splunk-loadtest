#!/usr/bin/env python3
"""Every N seconds print: log docs in eventing-logs bucket (business fn output) vs events the mock received.
Run during a test:  python3 watch_counts.py 10 120   (interval, total seconds)"""
import base64, json, os, sys, time, requests
API = os.environ.get("CAPELLA_API", "https://cloudapi.cloud.couchbase.com")
base = (f"{API}/v4/organizations/{os.environ['ORG_ID']}/projects/{os.environ['PROJECT_ID']}"
        f"/clusters/{os.environ['CLUSTER_ID']}")
H = {"Authorization": f"Bearer {os.environ['CAPELLA_API_KEY']}"}
def bid(n): return base64.urlsafe_b64encode(n.encode()).decode()
def items(bucket):
    r = requests.get(f"{base}/buckets/{bid(bucket)}", headers=H, timeout=30)
    if not r.ok:
        return f"HTTP{r.status_code}"
    j = r.json()
    st = j.get("stats", {})
    return st.get("itemCount", st)
def fstate(name):
    r = requests.get(f"{base}/eventingFunctions/{name}", headers=H, timeout=30)
    return r.json().get("status") if r.ok else f"HTTP{r.status_code}"
iv, total = float(sys.argv[1]), float(sys.argv[2])
t0 = time.time()
while time.time() - t0 < total:
    try:
        m = requests.get("http://127.0.0.1:8088/stats", timeout=5).json()
    except Exception:
        m = {}
    print(f"t={int(time.time()-t0):4d}s  logs_bucket_items={items('eventing-logs')}  data_items={items('data')}  mock_events={m.get('events')}  mock_reqs={m.get('reqs')}  busy={m.get('busy')}  biz={fstate('enrich_orders')}  ship={fstate('ship_logs')}", flush=True)
    time.sleep(iv)

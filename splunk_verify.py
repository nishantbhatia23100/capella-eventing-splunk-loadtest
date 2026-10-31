#!/usr/bin/env python3
"""Check a real-Splunk run by search: counts per level, duplicates, delay, and the comparison with what Eventing wrote.
  python3 splunk_verify.py <tag>      reads the run id from load_<tag>.log (line 1: run=NNNNNN) or load_<tag>_1.log
Env: SPLUNK_AUTH (user:pass), SPLUNK_MGMT, CB_CONNSTR, CB_USER, CB_PASS."""
import csv, io, json, os, re, subprocess, sys, requests, urllib3
urllib3.disable_warnings()
tag = sys.argv[1]
logf = next(f for f in (f"load_{tag}.log", f"load_{tag}_1.log") if os.path.exists(f))
run = re.match(r"run=(\S+)", open(logf).readline()).group(1)
mgmt = os.environ.get("SPLUNK_MGMT", "https://localhost:8089"); auth = tuple(os.environ["SPLUNK_AUTH"].split(":", 1))
def search(q):
    r = requests.post(f"{mgmt}/services/search/jobs/export", auth=auth, verify=False, timeout=600,
                      data={"search": q, "output_mode": "csv", "earliest_time": "-12h"})
    return list(csv.DictReader(io.StringIO(r.text)))
base = f'search index=couchbase sourcetype="couchbase:eventing" meta_id="load::{run}::*"'
lv = search(base + " | eval d=_indextime-_time | stats count avg(d) as avg perc95(d) as p95 max(d) as max by level | sort level")
tot = search(base + ' | stats count dc(meta_id) as orders | eval k=1')[0]
dup = search(base + " | stats count by meta_id, t, message | where count>1 | stats count as duplicated_events")
dup = int(dup[0]["duplicated_events"]) if dup else 0
exp = json.loads(subprocess.check_output([sys.executable, "expected_events.py", run]).decode())
got = int(tot["count"])
print(f"\n=== Splunk check for {tag} (run {run}) ===")
print(f"Eventing wrote {exp['total']} events ({exp['debug']} debug); Splunk has {got}; missing {exp['total']-got}; duplicated {dup}; orders seen {tot['orders']}")
for r in lv:
    print(f"  {r['level']:8s} {int(r['count']):7d}   created->searchable avg {float(r['avg']):5.1f}s  p95 {float(r['p95']):5.1f}s  max {float(r['max']):5.1f}s")

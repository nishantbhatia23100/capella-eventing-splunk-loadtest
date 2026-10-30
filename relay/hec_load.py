#!/usr/bin/env python3
"""Imitate Eventing shipper workers: N sequential callers POSTing HEC events as fast as the target answers.

A closed loop (each worker waits for the reply before the next call) is exactly how an Eventing
worker behaves, so calls/s per worker ~ 1 / call latency. Compare a slow target (Splunk-like) with a relay.

  python3 hec_load.py --target http://127.0.0.1:18088/services/collector/event --workers 1 --duration 10
  python3 hec_load.py --target ... --workers 4 --events-per-call 3
"""
import argparse, json, statistics, threading, time
import requests

ap = argparse.ArgumentParser()
ap.add_argument("--target", required=True)
ap.add_argument("--workers", type=int, default=1)
ap.add_argument("--duration", type=float, default=10)
ap.add_argument("--events-per-call", type=int, default=1)
ap.add_argument("--token", default="x")
ap.add_argument("--label", default="")
a = ap.parse_args()

lat, ok, bad = [], [0], [0]
lock = threading.Lock()
stop = time.time() + a.duration


def body():
    t = int(time.time() * 1000)
    return "".join(json.dumps({"time": t / 1000, "sourcetype": "couchbase:eventing", "index": "couchbase",
                               "event": {"t": t, "level": "info", "message": "x" * 120}})
                   for _ in range(a.events_per_call))


def worker():
    s = requests.Session()
    h = {"Authorization": f"Splunk {a.token}"}
    mine = []
    while time.time() < stop:
        t0 = time.time()
        try:
            r = s.post(a.target, data=body(), headers=h, timeout=30)
            good = r.status_code == 200
        except Exception:
            good = False
        mine.append(time.time() - t0)
        with lock:
            if good:
                ok[0] += 1
            else:
                bad[0] += 1
    with lock:
        lat.extend(mine)


ths = [threading.Thread(target=worker) for _ in range(a.workers)]
t0 = time.time()
[t.start() for t in ths]
[t.join() for t in ths]
el = time.time() - t0
lat.sort()
calls = ok[0] + bad[0]
print(f"{a.label or a.target}: workers={a.workers} calls/s={calls / el:.0f} events/s={ok[0] * a.events_per_call / el:.0f} "
      f"p50={lat[len(lat) // 2] * 1000:.1f}ms p95={lat[int(len(lat) * .95)] * 1000:.1f}ms failed={bad[0]}")

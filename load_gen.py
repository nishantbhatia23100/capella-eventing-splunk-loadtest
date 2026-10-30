#!/usr/bin/env python3
"""Rate-controlled order generator: inserts docs into the Eventing function's source collection.

Env vars (not needed with --dry-run): CB_CONNSTR (couchbases://...), CB_USER, CB_PASS

  python3 load_gen.py --rate 200 --duration 120            # 200 docs/s for 2 minutes
  python3 load_gen.py --rate 500 --duration 300 --workers 16
  python3 load_gen.py --dry-run --rate 50 --duration 5     # test pacing without a cluster

Docs match the repo's enrich_orders function (type=order, amount, category). Keys are
load::<run>::<n>, so reruns don't collide. Deleting them later:  DELETE FROM `data`.sales.orders WHERE META().id LIKE "load::%";
"""
import argparse, json, os, random, sys, threading, time
from datetime import datetime, timezone

CATS = ["electronics", "apparel", "grocery", "toys", "books"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=100, help="docs per second")
    ap.add_argument("--duration", type=float, default=60, help="seconds")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--bucket", default="data")
    ap.add_argument("--scope", default="sales")
    ap.add_argument("--collection", default="orders")
    ap.add_argument("--run", default=datetime.now(timezone.utc).strftime("%H%M%S"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--via-query", action="store_true",
                    help="insert through the query service over HTTPS (no Couchbase SDK; use if the SDK crashes)")
    ap.add_argument("--batch", type=int, default=20, help="docs per INSERT in --via-query mode")
    ap.add_argument("--ca-cert", default=os.environ.get("CB_CA_CERT", ""),
                    help="path to the cluster's root certificate (PEM) for --via-query TLS verification")
    ap.add_argument("--insecure", action="store_true",
                    help="skip TLS verification in --via-query mode (throwaway test clusters only)")
    a = ap.parse_args()

    col = None
    if not a.dry_run and not a.via_query:
        from datetime import timedelta
        from couchbase.auth import PasswordAuthenticator
        from couchbase.cluster import Cluster
        from couchbase.options import ClusterOptions
        opts = ClusterOptions(PasswordAuthenticator(os.environ["CB_USER"], os.environ["CB_PASS"]))
        if hasattr(opts, "apply_profile"):
            opts.apply_profile("wan_development")
        cluster = Cluster(os.environ["CB_CONNSTR"], opts)
        cluster.wait_until_ready(timedelta(seconds=30))
        col = cluster.bucket(a.bucket).scope(a.scope).collection(a.collection)

    total = int(a.rate * a.duration)
    sent = [0]
    errs = [0]
    lock = threading.Lock()
    t0 = time.time() + 1.0
    t_end = [t0]

    def work_query(w):
        import requests
        host = os.environ["CB_CONNSTR"].split("://", 1)[-1].split("/")[0].split(",")[0]
        url = f"https://{host}:18093/query/service"
        auth = (os.environ["CB_USER"], os.environ["CB_PASS"])
        ks = f"`{a.bucket}`.`{a.scope}`.`{a.collection}`"
        sess = requests.Session()
        sess.verify = False if a.insecure else (a.ca_cert or True)
        if a.insecure:
            import urllib3
            urllib3.disable_warnings()
        nb = (total + a.batch - 1) // a.batch
        for j in range(w, nb, a.workers):
            lo, hi = j * a.batch, min(total, (j + 1) * a.batch)
            delay = t0 + lo / a.rate - time.time()
            if delay > 0:
                time.sleep(delay)
            vals = []
            for i in range(lo, hi):
                doc = {"type": "order", "orderId": i, "run": a.run,
                       "customerId": f"cust::{i % 500}",
                       "amount": round(random.random() * 500, 2),
                       "category": CATS[i % len(CATS)], "status": "NEW",
                       "ts": datetime.now(timezone.utc).isoformat()}
                vals.append(f'("load::{a.run}::{i}", {json.dumps(doc)})')
            try:
                r = sess.post(url, auth=auth, timeout=60, json={
                    "statement": f"UPSERT INTO {ks} (KEY, VALUE) VALUES " + ",".join(vals)})
                ok = r.ok and r.json().get("status") == "success"
                if not ok:
                    raise RuntimeError(f"HTTP {r.status_code} {r.text[:300]}")
                with lock:
                    sent[0] += hi - lo
                    t_end[0] = max(t_end[0], time.time())
            except Exception as e:
                with lock:
                    errs[0] += hi - lo
                if errs[0] <= 5 * a.batch:
                    print("error:", e, file=sys.stderr)

    def work(w):
        for i in range(w, total, a.workers):
            delay = t0 + i / a.rate - time.time()
            if delay > 0:
                time.sleep(delay)
            doc = {"type": "order", "orderId": i, "run": a.run,
                   "customerId": f"cust::{i % 500}",
                   "amount": round(random.random() * 500, 2),
                   "category": CATS[i % len(CATS)], "status": "NEW",
                   "ts": datetime.now(timezone.utc).isoformat()}
            try:
                if col:
                    col.upsert(f"load::{a.run}::{i}", doc)
                with lock:
                    sent[0] += 1
                    t_end[0] = max(t_end[0], time.time())
            except Exception as e:
                with lock:
                    errs[0] += 1
                if errs[0] <= 5:
                    print("error:", e, file=sys.stderr)

    target = work_query if (a.via_query and not a.dry_run) else work
    ths = [threading.Thread(target=target, args=(w,)) for w in range(a.workers)]
    for t in ths:
        t.start()
    print(f"run={a.run} target {a.rate}/s for {a.duration}s ({total} docs), {a.workers} workers{' [dry-run]' if a.dry_run else ''}")
    last = 0
    while any(t.is_alive() for t in ths):
        time.sleep(5)
        with lock:
            s, e = sent[0], errs[0]
        print(f"  sent={s} errors={e} rate~{(s - last) / 5:.0f}/s")
        last = s
    for t in ths:
        t.join()
    el = max(t_end[0] - t0, 1e-9)
    print(f"done: sent={sent[0]} errors={errs[0]} achieved={sent[0] / el:.0f}/s over {el:.0f}s")
    if sent[0] / el < 0.9 * a.rate:
        print("WARNING: achieved rate is below target; raise --workers or run closer to the cluster")


if __name__ == "__main__":
    main()

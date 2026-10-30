#!/usr/bin/env python3
"""Scrape Capella's per-node Prometheus metrics during a test (CPU + Eventing + a few others).

Env: CB_CONNSTR, CB_USER, CB_PASS   (DB user allowed to read stats)
  python3 scrape_metrics.py 5 300 metrics_run.jsonl     # every 5 s for 300 s
  python3 scrape_metrics.py --summary metrics_run.jsonl  # peak/trend summary
"""
import json, os, re, sys, time
import requests

KEEP = re.compile(r"^(sys_cpu_(utilization|host_utilization)_rate|sys_mem_free|sys_cpu_burst_rate|eventing_[a-z_]+)$")
LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eE]+|NaN|\+Inf|-Inf)')
CA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "cluster-root.pem")


def targets(host, auth):
    r = requests.get(f"https://{host}:18091/prometheus_sd_config", auth=auth, verify=CA, timeout=20)
    r.raise_for_status()
    return [t for g in r.json() for t in g.get("targets", [])]


def scrape():
    host = os.environ["CB_CONNSTR"].split("://", 1)[-1].split("/")[0].split(",")[0]
    auth = (os.environ["CB_USER"], os.environ["CB_PASS"])
    iv, total, out = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
    tg = targets(host, auth)
    print("nodes:", tg, flush=True)
    t0 = time.time()
    with open(out, "w") as f:
        while time.time() - t0 < total:
            now = round(time.time() - t0, 1)
            for t in tg:
                try:
                    r = requests.get(f"https://{t}/metrics", auth=auth, verify=CA, timeout=15)
                except Exception as e:
                    f.write(json.dumps({"t": now, "node": t, "error": str(e)[:80]}) + "\n")
                    continue
                for line in r.text.splitlines():
                    m = LINE.match(line)
                    if m and KEEP.match(m.group(1)):
                        lab = m.group(2) or ""
                        fn = re.search(r'function_name="([^"]+)"', lab)
                        f.write(json.dumps({"t": now, "node": t.split(".")[0], "m": m.group(1),
                                            "fn": fn.group(1) if fn else None, "v": m.group(3)}) + "\n")
            f.flush()
            time.sleep(iv)


def summary(path):
    rows = [json.loads(l) for l in open(path)]
    errs = [r for r in rows if "error" in r]
    print(f"{len(rows)} samples, {len(errs)} errors")
    by = {}
    for r in rows:
        if "m" not in r:
            continue
        try:
            v = float(r["v"])
        except ValueError:
            continue
        by.setdefault((r["m"], r["fn"], r["node"]), []).append((r["t"], v))
    for (m, fn, node), s in sorted(by.items(), key=lambda x: (x[0][0], str(x[0][1]), x[0][2])):
        vals = [v for _, v in s]
        if m.startswith("sys_cpu") or max(vals) != min(vals):
            print(f"{m:44s} {str(fn or ''):16s} {node:12s} min={min(vals):.1f} max={max(vals):.1f} last={vals[-1]:.1f}")


if __name__ == "__main__":
    summary(sys.argv[2]) if sys.argv[1] == "--summary" else scrape()

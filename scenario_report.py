#!/usr/bin/env python3
"""Summarise one scenario run: python3 scenario_report.py TAG "<SHIPPERS>" "<MOCKS>" """
import csv, glob, json, os, re, sys
tag, shippers, mocks = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""
env = dict(l.strip().split("=", 1) for l in open(f"timing_{tag}.env") if "=" in l)
ms, ls, le, de = (int(env[k]) for k in ("MOCK_START", "LOAD_START", "LOAD_END", "DRAIN_END"))
exp = json.load(open(f"expected_{tag}.json")) if os.path.exists(f"expected_{tag}.json") else {}
fnum = lambda v: float(v) if v not in ("", "nan", None) else float("nan")
ok = lambda x: x == x

mock_info, recv, recv_by_port = [], 0, {}
for m in mocks.split():
    port, lat = m.split(":")[0], m.split(":")[1]
    p = f"run_{tag}_p{port}.csv"
    if not os.path.exists(p): continue
    rows = list(csv.DictReader(open(p)))
    act = [r for r in rows if fnum(r["events_s"]) > 0]
    if not act: mock_info.append(dict(port=port, lat=lat, events=0)); continue
    tot = int(rows[-1]["total_events"]); recv += tot; recv_by_port[port] = tot
    last_active = int(act[-1]["elapsed_s"]) + ms
    at_end = [r for r in rows if abs(int(r["elapsed_s"]) + ms - le) <= 5 and fnum(r["lag_p95"]) == fnum(r["lag_p95"])]
    g = lambda col, f=max: f([fnum(r[col]) for r in act if col in r and ok(fnum(r[col]))] or [float("nan")])
    mock_info.append(dict(port=port, lat=lat, events=tot, peak_lag95=g("lag_p95"), peak_lagmax=g("lag_max"),
                          lag_end95=(fnum(at_end[0]["lag_p95"]) if at_end else float("nan")),
                          drain_s=last_active - le, peak_eps=g("events_s"),
                          hi95=g("lag_hi_p95"), dbg95=g("lag_dbg_p95"), busy=sum(fnum(r["busy_s"]) for r in rows) * 5))

cpu_peak = cpu_nodes = backlog_peak = backlog_zero = None
mp = f"metrics_{tag}.jsonl"
if os.path.exists(mp):
    cpu, bl = {}, {}
    for l in open(mp):
        r = json.loads(l)
        if "m" not in r: continue
        try: v = float(r["v"])
        except ValueError: continue
        if r["m"] == "sys_cpu_utilization_rate": cpu.setdefault(r["t"], {})[r["node"]] = v
        if r["m"] == "eventing_dcp_backlog": bl[(r["t"], r["node"])] = bl.get((r["t"], r["node"]), 0) + v
    if cpu:
        cpu_peak = max(max(d.values()) for d in cpu.values())
        cpu_nodes = max(sum(d.values()) / len(d) for d in cpu.values())
    tt = {}
    for (t, n), v in bl.items(): tt[t] = tt.get(t, 0) + v
    if tt:
        backlog_peak = max(tt.values())
        ts = sorted(tt); pk = max(ts, key=lambda t: tt[t])
        backlog_zero = next((t for t in ts if t > pk and tt[t] <= 1), None)

failures = None
if os.path.exists(f"errs_{tag}.txt"):
    m = re.search(r"failure records: (\d+)", open(f"errs_{tag}.txt").read()); failures = int(m.group(1)) if m else None
relay = None
if os.path.exists(f"relay_{tag}.csv"):
    rr = [l.strip().split(",") for l in open(f"relay_{tag}.csv") if l.count(",") == 3]
    if rr:
        acc = [(int(a), int(b)) for a, b, c, d in rr]; final = acc[-1][1]
        t_acc = next((t for t, a in acc if a >= final), None)
        relay = dict(accepted=final, accept_done_after_load_s=(t_acc - le) if t_acc else None, peak_queue=max(int(d) for *_, d in rr))

print(f"\n=== {tag} ===")
print(f"load: {int(le-ls)} s | delivery wait after load: {de-le} s{' (TIMEOUT: not fully delivered)' if env.get('DRAIN_TIMEOUT')=='1' else ''}")
print(f"expected events {exp.get('total','?')} (debug {exp.get('debug','?')}, other {exp.get('nondebug','?')}) | received {recv} | "
      f"missing {(exp['total']-recv) if exp else '?'} | failure records {failures}")
for mi in mock_info:
    if mi["events"] == 0: print(f"  mock :{mi['port']} ({mi['lat']} ms): nothing received"); continue
    print(f"  mock :{mi['port']} ({mi['lat']} ms): {mi['events']} events | peak lag p95 {mi['peak_lag95']:.0f}s max {mi['peak_lagmax']:.0f}s | "
          f"lag p95 at load end {mi['lag_end95']:.0f}s | delivered {mi['drain_s']:+d}s after load end | peak {mi['peak_eps']:.0f} events/s | "
          f"non-debug lag p95 {mi['hi95']:.0f}s, debug lag p95 {mi['dbg95']:.0f}s | busy 503s {mi['busy']:.0f}")
if cpu_peak is not None: print(f"  cluster CPU: peak node {cpu_peak:.0f}%, peak mean {cpu_nodes:.0f}% | Eventing DCP backlog peak {backlog_peak:.0f}" + (f", back to ~0 at t={backlog_zero:.0f}s" if backlog_zero else ""))
if relay: print(f"  relay: Eventing finished sending {relay['accept_done_after_load_s']} s after load end; peak relay queue {relay['peak_queue']} batches")
new = not os.path.exists("scenario_results.csv")
with open("scenario_results.csv", "a", newline="") as f:
    w = csv.writer(f)
    if new: w.writerow(["tag", "shippers", "mocks", "expected", "received", "failures", "peak_lag95", "lag_end95", "delivered_after_load_s", "peak_events_s", "cpu_peak", "backlog_peak", "timeout"])
    w.writerow([tag, shippers.replace("\n", ";").replace("|", ":")[:200], mocks, exp.get("total"), recv, failures,
                max([m.get("peak_lag95", 0) for m in mock_info] or [0]), max([m.get("lag_end95", 0) for m in mock_info] or [0]),
                max([m.get("drain_s", 0) for m in mock_info] or [0]), sum(m.get("peak_eps", 0) for m in mock_info), cpu_peak, backlog_peak, env.get("DRAIN_TIMEOUT")])

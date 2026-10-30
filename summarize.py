#!/usr/bin/env python3
"""Compare mock_hec CSV runs: python3 summarize.py run_A.csv run_B.csv run_C.csv run_D.csv"""
import csv, statistics, sys

def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError):
        return float("nan")

print(f"{'run':<16}{'events':>8}{'active_s':>9}{'med evt/s':>10}{'peak evt/s':>11}{'peak lag95':>11}{'peak e2e95':>11}{'busy':>6}")
for p in sys.argv[1:]:
    rows = list(csv.DictReader(open(p)))
    act = [r for r in rows if f(r, "events_s") > 0]
    if not act:
        print(f"{p:<16} no traffic")
        continue
    span = int(act[-1]["elapsed_s"]) - int(act[0]["elapsed_s"]) + 5
    e2e = [f(r, "e2e_p95") for r in act if f(r, "e2e_p95") == f(r, "e2e_p95")]
    print(f"{p:<16}{int(rows[-1]['total_events']):>8}{span:>9}"
          f"{statistics.median(f(r, 'events_s') for r in act):>10.0f}"
          f"{max(f(r, 'events_s') for r in act):>11.0f}"
          f"{max(f(r, 'lag_p95') for r in act):>11.0f}"
          f"{(max(e2e) if e2e else float('nan')):>11.0f}"
          f"{sum(f(r, 'busy_s') for r in rows) * 5:>6.0f}")

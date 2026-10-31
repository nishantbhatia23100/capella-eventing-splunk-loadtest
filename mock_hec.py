#!/usr/bin/env python3
"""Mock Splunk HEC for load-testing Couchbase Eventing log shippers.

Behaves like /services/collector/event but with a configurable service time and connection
limit, and reports delivery lag (receive time minus the log's own timestamp).

  python3 mock_hec.py --latency-ms 50 --max-conns 8 --csv run_A.csv

Expose it to Capella with:  ngrok http 8088   (use the https URL as the cURL binding)

Lag is taken from, in order: event["@timestamp"] (ISO), event["t"] (epoch ms), or each
entry of event["events"][*]["t"]. Envelope "time" is NOT used: shippers often set it to ship time.
"""
import argparse, csv, gzip, json, sys, threading, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

args = None
lock = threading.Lock()
active = 0
down = False   # outage switch: GET /ctl?down=1 makes every POST return 503, /ctl?down=0 restores service
cum = {"reqs": 0, "events": 0, "busy": 0, "bad": 0, "peak_active": 0}
win = {"reqs": 0, "events": 0, "busy": 0, "bad": 0, "lags": [], "e2e": [], "dbg": [], "hi": []}
start_ts = time.time()


def parse_iso(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def origin_times(env):
    ev = env.get("event") if isinstance(env, dict) else None
    out = []
    if isinstance(ev, dict):
        if isinstance(ev.get("@timestamp"), str):
            t = parse_iso(ev["@timestamp"])
            if t:
                out.append(t)
        elif isinstance(ev.get("t"), (int, float)):
            out.append(ev["t"] / 1000.0)
        elif isinstance(ev.get("events"), list):
            out += [e["t"] / 1000.0 for e in ev["events"] if isinstance(e, dict) and isinstance(e.get("t"), (int, float))]
    return out


def order_time(env):
    ev = env.get("event") if isinstance(env, dict) else None
    if isinstance(ev, dict) and isinstance(ev.get("order_ts"), str):
        return parse_iso(ev["order_ts"])
    return None


def split_events(body):
    dec, i, n, out = json.JSONDecoder(), 0, len(body), []
    while i < n:
        while i < n and body[i] in " \r\n\t":
            i += 1
        if i >= n:
            break
        obj, i = dec.raw_decode(body, i)
        out.append(obj)
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        global down
        if self.path.startswith("/ctl"):
            down = "down=1" in self.path
            return self._send(200, {"down": down})
        if self.path.startswith("/stats"):
            with lock:
                self._send(200, dict(cum, active=active, uptime_s=round(time.time() - start_ts, 1)))
        else:
            self._send(200, {"text": "HEC is healthy", "code": 17})

    def do_POST(self):
        global active
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if args.token:
            a = self.headers.get("Authorization", "")
            if a.split(" ", 1)[-1] != args.token:
                return self._send(403, {"text": "Invalid token", "code": 4})
        if args.dump and cum.get("dumped", 0) < args.dump:
            with open("dump.txt", "a") as f:
                f.write(f"--- headers: ct={self.headers.get('Content-Type')} enc={self.headers.get('Content-Encoding')} len={len(raw)}\n{raw[:1500]!r}\n")
            cum["dumped"] = cum.get("dumped", 0) + 1
        if down:
            with lock:
                cum["down_rejects"] = cum.get("down_rejects", 0) + 1
            return self._send(503, {"text": "Server is busy", "code": 9})
        with lock:
            if active >= args.max_conns:
                cum["busy"] += 1; win["busy"] += 1
                return self._send(503, {"text": "Server is busy", "code": 9})
            active += 1
            cum["peak_active"] = max(cum["peak_active"], active)
        try:
            try:
                data = gzip.decompress(raw) if self.headers.get("Content-Encoding", "").lower() == "gzip" else raw
                evs = split_events(data.decode("utf-8"))
            except Exception:
                with lock:
                    cum["bad"] += 1; win["bad"] += 1
                return self._send(400, {"text": "Invalid data format", "code": 6})
            time.sleep((args.latency_ms + args.per_event_ms * len(evs)) / 1000.0
                       + (args.jitter_ms / 1000.0) * (time.time() % 1))
            now = time.time()
            lags = [now - t for e in evs for t in origin_times(e)]
            e2e = [now - t for t in (order_time(e) for e in evs) if t]
            lv = {"debug": [], "hi": []}   # "hi" = info, warning, error
            for e in evs:
                ev = e.get("event") if isinstance(e, dict) else None
                k = "debug" if isinstance(ev, dict) and ev.get("level") == "debug" else "hi"
                lv[k] += [now - t for t in origin_times(e)]
            for e in evs:
                ev = e.get("event") if isinstance(e, dict) else None
                name = ev.get("level", "?") if isinstance(ev, dict) else "?"
                bl = cum.setdefault("by_level", {})
                bl[name] = bl.get(name, 0) + 1
            with lock:
                cum["reqs"] += 1; win["reqs"] += 1
                cum["events"] += len(evs); win["events"] += len(evs)
                win["lags"] += lags
                win["e2e"] += e2e
                win["dbg"] += lv["debug"]; win["hi"] += lv["hi"]
            self._send(200, {"text": "Success", "code": 0})
        finally:
            with lock:
                active -= 1


def pct(v, p):
    return v[min(len(v) - 1, int(len(v) * p))] if v else float("nan")


def reporter():
    w = None
    if args.csv:
        f = open(args.csv, "w", newline="")
        w = csv.writer(f)
        w.writerow(["elapsed_s", "reqs_s", "events_s", "busy_s", "bad_s", "lag_p50", "lag_p95", "lag_max", "total_events", "e2e_p50", "e2e_p95", "lag_dbg_p95", "lag_dbg_max", "lag_hi_p95", "lag_hi_max"])
    print(f"{'t(s)':>6} {'req/s':>7} {'evt/s':>8} {'busy/s':>7} {'lag p50':>8} {'p95':>8} {'max':>8} {'total':>9} {'e2e p50':>9} {'e2e p95':>9}", flush=True)
    last = time.time()
    while True:
        time.sleep(args.report_sec)
        now = time.time()
        dt = now - last
        last = now
        with lock:
            r, e, b, bad, lags, e2e = win["reqs"], win["events"], win["busy"], win["bad"], sorted(win["lags"]), sorted(win["e2e"])
            dbg, hi = sorted(win["dbg"]), sorted(win["hi"])
            win.update(reqs=0, events=0, busy=0, bad=0, lags=[], e2e=[], dbg=[], hi=[])
            total = cum["events"]
        row = [round(now - start_ts), round(r / dt, 1), round(e / dt, 1), round(b / dt, 1), round(bad / dt, 1),
               round(pct(lags, .5), 2), round(pct(lags, .95), 2), round(lags[-1], 2) if lags else float("nan"), total,
               round(pct(e2e, .5), 2), round(pct(e2e, .95), 2),
               round(pct(dbg, .95), 2), round(dbg[-1], 2) if dbg else float("nan"), round(pct(hi, .95), 2), round(hi[-1], 2) if hi else float("nan")]
        print(f"{row[0]:>6} {row[1]:>7} {row[2]:>8} {row[3]:>7} {row[5]:>8} {row[6]:>8} {row[7]:>8} {row[8]:>9} {row[9]:>9} {row[10]:>9}", flush=True)
        if w:
            w.writerow(row); f.flush()


def main():
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--latency-ms", type=float, default=50, help="base service time per request")
    ap.add_argument("--per-event-ms", type=float, default=0.0, help="extra service time per event in a request")
    ap.add_argument("--jitter-ms", type=float, default=10)
    ap.add_argument("--max-conns", type=int, default=8, help="concurrent in-flight requests before 503 'Server is busy'")
    ap.add_argument("--token", default="", help="require this HEC token (omit to accept any)")
    ap.add_argument("--report-sec", type=float, default=5)
    ap.add_argument("--csv", default="")
    ap.add_argument("--dump", type=int, default=0, help="write the first N raw request bodies to dump.txt")
    args = ap.parse_args()
    threading.Thread(target=reporter, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), H)
    srv.daemon_threads = True
    print(f"mock HEC on :{args.port}  latency={args.latency_ms}ms max_conns={args.max_conns}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nfinal:", json.dumps(cum))


if __name__ == "__main__":
    main()

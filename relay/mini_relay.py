#!/usr/bin/env python3
"""Reference HEC relay (stdlib + requests). Same behaviour as the OTel Collector config, for local testing.

Accepts POST /services/collector/event (stacked HEC JSON), acknowledges immediately after queueing,
and a flusher batches events and forwards them to a downstream HEC endpoint over persistent connections.

  python3 mini_relay.py --port 18089 --downstream http://127.0.0.1:18088/services/collector/event
"""
import argparse, json, queue, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests

args = None
q = None
stats = {"accepted": 0, "forwarded": 0, "batches": 0, "failed": 0, "rejected": 0}
lock = threading.Lock()


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
        with lock:
            self._send(200, dict(stats, queue=q.qsize()))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            evs = split_events(raw.decode("utf-8"))
        except Exception:
            return self._send(400, {"text": "Invalid data format", "code": 6})
        if q.maxsize and q.qsize() + len(evs) > q.maxsize:
            with lock:
                stats["rejected"] += len(evs)
            return self._send(503, {"text": "Server is busy", "code": 9})
        for e in evs:
            q.put(json.dumps(e))
        with lock:
            stats["accepted"] += len(evs)
        self._send(200, {"text": "Success", "code": 0})


def flusher():
    sess = requests.Session()
    headers = {"Authorization": f"Splunk {args.token}"} if args.token else {}
    while True:
        batch = []
        deadline = time.time() + args.timeout
        while len(batch) < args.batch and time.time() < deadline:
            try:
                batch.append(q.get(timeout=max(0.01, deadline - time.time())))
            except queue.Empty:
                break
        if not batch:
            continue
        body = "".join(batch)
        for attempt in range(4):
            try:
                r = sess.post(args.downstream, data=body, headers=headers, timeout=30)
                if r.status_code == 200:
                    with lock:
                        stats["forwarded"] += len(batch)
                        stats["batches"] += 1
                    break
            except Exception:
                pass
            time.sleep(min(2 ** attempt, 8))
        else:
            with lock:
                stats["failed"] += len(batch)


def main():
    global args, q
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18089)
    ap.add_argument("--downstream", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--batch", type=int, default=500, help="events per downstream request")
    ap.add_argument("--timeout", type=float, default=1.0, help="max seconds an event waits for its batch")
    ap.add_argument("--flushers", type=int, default=2, help="parallel downstream requests")
    ap.add_argument("--max-queue", type=int, default=200000)
    args = ap.parse_args()
    q = queue.Queue(maxsize=args.max_queue)
    for _ in range(args.flushers):
        threading.Thread(target=flusher, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), H)
    srv.daemon_threads = True
    print(f"relay on :{args.port} -> {args.downstream} batch={args.batch} timeout={args.timeout}s flushers={args.flushers}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

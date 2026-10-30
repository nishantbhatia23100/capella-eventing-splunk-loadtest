# Results: what was tested and what it showed

## The problem

A customer's Eventing functions write log lines as documents into a logs collection. A second "shipper"
function POSTs each document to Splunk HEC. Under load, logs reach Splunk hours late. Adding workers
(4 → 8) did not change the peak rate (~11K events/min), and Splunk sometimes rejected calls with
"active connection limit reached". We built the pipeline on a test cluster, drove it with a known load and
changed one thing per run.

## Method

- **Load:** `load_gen.py` inserts orders at a fixed rate (200/s for 60 s = 12,000 orders). The business function
  `enrich_orders` writes about 3 log lines per order.
- **Splunk stand-in:** `mock_hec.py` accepts HEC posts with a configurable service time and connection limit,
  and records, every 5 s, the delivery rate and two lags: **lag** (log line created → received) and **e2e**
  (order inserted → received). Isolating Splunk this way separates Eventing's behaviour from Splunk's capacity.
- **Test cluster:** 3 nodes, 4 vCPU / 16 GB each, every node running Data, Index, Query and Eventing.
- **A run is "drained"** when no new events arrive for 45 s. Every run in the final matrix also recorded a
  row for each failed shipper call (variant F) so no loss could go unnoticed.

## Tests, in the order they were run

| # | Test | Why | Outcome |
|---|---|---|---|
| 1 | **A: baseline.** One doc and one call per log line, 1 worker | Reproduce the symptom | Delivery capped at ~50 calls/s; the last log line was **719 s (12 min) late** |
| 2 | **C: one doc per order** (all lines batched in one doc), 1 worker | Fewer mutations and calls | Peak lag 190 s; calls 3× fewer |
| 3 | **D1: batched HEC call** (all of an order's events stacked in one POST), 1 worker, 50 orders/s | Does one call per doc hold? | Clean; ~150 log lines/s per worker |
| 4 | **E: filtered**: drop debug, sample 10% of info, keep warn/error; 1 worker at 200 orders/s | Cut volume at the source | No backlog, lag 1-2 s (shipped calls −94%) |
| 5 | **Early multi-worker runs** (B8, B64, D, D2w, R1) | Does parallelism help? | **Invalid.** Delivery stopped after ~15-45 s. Cause found later: the free ngrok tunnel rate-limited Capella (see 6) |
| 6 | **Failure-recording shipper (F)** on that tunnel | Find where calls were going | 7,716 of 12,000 calls failed: 483 × HTTP 429 and 7,233 × TLS connect errors from the tunnel. Eventing counted them all as **successful** executions |
| 7 | **Node metrics scrape** during a run | CPU or Eventing limit? | CPU peaked at 49%; zero Eventing failures, timeouts or worker restarts |
| 8 | **Relay (OTel Collector), local** | A buffering HEC relay in front of Splunk | Config validated with the real image (two bugs fixed). Loopback demo: 1 worker 16 → 654 calls/s; 16 workers 1,386 events/s with 0 failures vs 12,249 rejected posting directly |
| 9 | **Final matrix on a non-throttling tunnel** (cloudflared) | Redo 5 properly | See below. 0 failed calls in every run |

## Final matrix (200 orders/s, 60 s, ~36.8K events each)

| Run | Design | Workers | Splunk stand-in | Peak lag | Peak events/s | Drain |
|---|---|---|---|---|---|---|
| A | one doc per log line | 1 | 50 ms | **719 s** | 50 | 781 s |
| X1 | one doc per order | 1 | 5 ms | 315 s | 118 | 380 s |
| X2 | one doc per order | 2 | 5 ms | 146 s | 225 | 210 s |
| X4 | one doc per order | 4 | 5 ms | 45 s | 472 | 110 s |
| X8 | one doc per order | 8 | 5 ms | **4 s** | 703 | 70 s |
| Y4 | one doc per order | 4 | 50 ms | 66 s | 362 | 130 s |
| P8 | one doc per log line | 8 | 5 ms | 103 s | 296 | 170 s |
| Z1 | via relay | 1 | 50 ms | 302 s | 124 | 365 s |
| Z4 | via relay | 4 | 50 ms | 40 s | 498 | 105 s |

Splunk-side request counts for the same 36.8K events: **~11,986** (direct, X4), **~361** (relay, Z1), **~99** (relay, Z4).

## What it shows

1. **Workers scale** when nothing downstream limits them (peak lag 315 → 146 → 45 → 4 s for 1, 2, 4, 8 workers).
   One worker handled ~37 calls/s on this network path: throughput per worker is roughly 1 ÷ round-trip time.
2. **One doc per execution matters as much as workers.** With the same 8 workers, per-line docs peaked at
   103 s lag against 4 s.
3. **Call latency matters moderately:** 50 ms instead of 5 ms cost ~25% throughput at 4 workers.
4. **A relay protects Splunk** (30-120× fewer requests, zero loss, durable queue). It does not speed Eventing up
   unless the relay is closer (lower round trip) than Splunk.
5. **Eventing counts a rejected or failed HTTP call as a success** unless the code checks. Delivery must be
   verified outside the function stats: record non-200 responses and exceptions (variant F).
6. **A flat ceiling that doesn't move with worker count** (the customer's 4 vs 8 workers) points to a limit
   between Eventing and Splunk (rate limit, connection limit, load balancer, HEC concurrency), not to Eventing's
   own scaling: exactly what the free ngrok tunnel did to our early runs.

## Not tested / caveats

- Real Splunk, and the customer's network path. The mock removes Splunk's own limits.
- The customer's timer-based batching design.
- A relay close to Eventing (same region). Round-trip savings are predicted, not measured.
- A single small cluster; numbers compare designs and are not forecasts for another environment.
- The relay's Collector config was validated and run locally, but option names should be re-checked for your version.

## Recommendations

1. Record every non-200 response and exception from the shipper (dead-letter collection); alert on it.
2. Write one log document per execution; drop debug, sample info, keep warn/error.
3. Size workers: workers ≥ calls per second × round-trip time (seconds).
4. Put a batching HEC relay between Eventing and Splunk; run two or more replicas.
5. Test the shipper against an endpoint that answers 200 instantly. If the ceiling disappears, the limit is in the path to Splunk.
6. Set a TTL on the logs collection, longer than the worst-case backlog.

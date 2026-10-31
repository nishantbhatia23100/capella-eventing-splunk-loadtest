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
| 10 | **Runtime log level (variant G)**: config document read per execution; level flipped debug → warning → debug during one run, 100 orders/s for 90 s | Can they choose what is logged without redeploying? | Yes. Delivered rate fell from ~200 to **8 events/s** while the config said `warning` (about 20 s after the flip, once the earlier backlog drained) and recovered after setting `debug`. Total events 18,463 against ~18,400 predicted; 0 failed calls |
| 11 | **Real Splunk, direct** (shipper F, 2 workers, 6,000 orders at 100/s, via tunnel) | The mock hides Splunk's own behaviour | 18,442 new events indexed (expected ~18,420); every call accepted; 0 failure records; all indexed ~47 s after the load ended |
| 12 | **Real Splunk via the relay** (Collector → Splunk HEC) | Does the relay work with real HEC and keep the index? | 18,394 new events indexed; relay counters 18,395 in / 18,395 out / 0 failed / queue empty; events kept their `couchbase` index |
| 13 | **Runtime log level on real Splunk** (variant G, debug → warning → debug) | Same as 10, counted by Splunk | 18,472 new events against ~18,400 predicted; 0 failures |
| 14 | **Re-run on a fresh Splunk Enterprise trial (10.4.1) with search enabled**: S1 direct, S2 via relay, S3 level flip, then Splunk searches | Add what counting alone could not show: per-level counts and indexing delay | Every run: 0 failure records; per-level counts match prediction exactly (section below) |

Setup problems met with the real Splunk (an old demo container), and how they showed up, are listed in the README.

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
   One worker handled ~38-40 calls/s on this network path. (Correction: an earlier version of this note said
   "1 ÷ round-trip time per worker". The full-volume tests below show a worker keeps several calls in flight at once,
   about 6 by our fit, so measure calls/s per worker on your own path instead of computing it.)
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

## Full volume: every level kept, nothing filtered

Question: can all logs, debug included, be shipped without cutting anything? Every run below uses the
one-document-per-order business function with **no filtering** (2 debug + 1 info + ~6% warning/error per order,
about 3.07 events per order) and shipper F with failure records. "Expected" is what the business function wrote,
counted in Capella by SQL++; "missing" is expected minus received. Cluster: 3 nodes x 4 vCPU, all services shared.
Peak lag is the highest 5-second p95 of (received - log created). Splunk is a mock with a set service time, reached
through a Cloudflare tunnel (the round trip to it is ~150 ms by our fit, so absolute lags are for this path only).

**Scale (fast endpoint, 5 ms):**

| Run | Orders/s | Workers | Events | Missing | Peak lag p95 | Peak events/s | Peak node CPU |
|---|---|---|---|---|---|---|---|
| B200w8 | 200 | 8 | 36,847 | 0 | 0.7 s | 630 | 46% |
| S400w8 | 400 | 8 | 73,685 | 0 | **30 s** (delivered 30 s after load) | 972 | 55% |
| S400w16 | 400 | 16 | 73,606 | 0 | 0.9 s | 1,260 | 59% |
| S800w16 | 800 | 16 | 147,388 | 0 | **31 s** | 1,865 | 77% |
| S800w32 | 800 | 32 | 147,344 | 0 | 1.8 s | 2,698 | 75% |
| SU10 (10 min) | 200 | 8 | 368,422 | 0 | 1.7 s | 720 | 49% |
| BU (100, 400, 100) | burst | 16 | 110,551 | 0 | 1.5 s | 1,273 | 58% |

**Slower Splunk, direct (200 orders/s):**

| Run | Splunk stand-in | Workers | Missing | Peak lag p95 |
|---|---|---|---|---|
| L100w16 / L100w32 | 100 ms | 16 / 32 | 0 / 0 | 0.9 s / 0.6 s |
| L200w32 / L200w64 | 200 ms | 32 / 64 | 0 / 0 | 0.9 s / 0.6 s |
| L400w16 | 400 ms | 16 | 0 | **25 s** (delivered 26 s after load) |
| L400w32 | 400 ms | 32 | 0 | 2.3 s |
| L400w64 | 400 ms | 64 | **27** (9 calls got HTTP 429 from the tunnel) | 1.9 s |

**Relay next to Eventing, 400 ms Splunk behind it:**

| Run | Orders/s | Workers | Missing | Peak lag p95 |
|---|---|---|---|---|
| R400w8 | 200 | 8 | 0 | 2.4 s |
| R400w4 | 200 | 4 | 0 | **22.6 s** (4 workers cap at ~170 calls/s on this path) |
| R800w32 | 800 | 32 | 0 | 2.6 s (147,361 events) |

**Splunk outage of 40 s in the middle of a 120 s run (200 orders/s, 8 workers):**

| Run | Path | Events expected / received | Missing | Failure records | Peak lag p95 |
|---|---|---|---|---|---|
| OD | direct | 73,637 / 49,040 | **24,597 (33%)** | 8,022 (HTTP 503) | 1.0 s (the rest were dropped) |
| OR | via relay | 73,697 / 73,697 | **0** | 0 | 62 s during the outage; caught up 6 s after the load ended |

**Priority isolation (two shipper functions on the same log collection, split by level; 100 orders/s,
non-debug events go to a fast endpoint, debug events to a 400 ms one):**

| Run | Design | Non-debug lag p95 | Debug lag p95 | Missing |
|---|---|---|---|---|
| I0c | one shipper, 8 workers, all levels, 400 ms endpoint | 29 s | 29 s | 0 |
| I1b | `ship_logs` 8 workers (info, warning, error) + `ship_debug` 4 workers (debug) | **0 s** | 94 s | 0 |

I1b uses 12 workers against I0c's 8, so it is not an equal-worker comparison. An equal-worker pair (6 + 2 against 8) was
not completed (the laptop went to sleep mid-run).

What it shows:

1. **Keeping every level is feasible.** 800 orders/s (about 2,700 events/s, all levels) held a p95 lag of ~2 s with 32 workers, with nothing
   missing, on three shared 4 vCPU nodes (node CPU peaked at 77%). Worker count is the lever: 16 workers at 800 orders/s
   fell 31 s behind and 8 workers at 400 orders/s fell 30 s behind, then both caught up.
2. **A slower Splunk costs workers.** Per worker we saw ~40 calls/s with a fast endpoint and ~11 calls/s with a 400 ms
   one. So at 400 ms, 16 workers could not hold 200 orders/s but 32 could.
3. **A relay next to Eventing makes Splunk's speed irrelevant to the workers.** With a 400 ms Splunk behind it, 8 workers
   held 200 orders/s and 32 held 800 orders/s, the same as with a fast endpoint. (The relay was reached over the same tunnel, so this
   shows the effect of the downstream delay, not of a second region.)
4. **An outage is where "ship everything" is decided.** Direct, a 40 s Splunk outage lost a third of the events (the shipper
   saw HTTP 503; Eventing's own statistics counted every call as a success). The failure records caught every one, and each record's key names the
   log document, so those events can be replayed from the logs collection. Through the relay nothing was lost, because the
   Collector queues on disk and retries.
5. **Fan-out by level isolates the slow path.** Two shipper functions on the same collection, each shipping only its levels, kept
   non-debug logs at 0 s lag while the debug path was 94 s behind. It costs one extra function and one more set of workers;
   the debug path must still be sized, or it lags.
6. **Tunnel limits are real.** The only losses outside the outage test (27 events in L400w64) were HTTP 429s from the free tunnel at a burst of
   128+ connections; only the failure records showed them.

Not yet measured: the same full-volume runs against real Splunk (the Docker disk filled up), a relay in a second region, and the
equal-worker isolation pair.

## Real Splunk, verified by search (fresh trial, test 14)

100 orders/s for 60 s (S1, S2) or 90 s (S3), shipper F or variant G, 2 shipper workers, through cloudflared tunnels.
Counts and delay come from Splunk searches. Delay = `_indextime - _time`, where `_time` is when Eventing created the log line.

| Run | debug | info | warning | error | Total | Delay avg / p95 / max (s) |
|---|---|---|---|---|---|---|
| S1 direct | 12,000 | 6,000 | 242 | 182 | 18,424 | 9.0 / 18.7 / 24.2 |
| S2 via relay | 12,000 | 6,000 | 227 | 187 | 18,414 | 8.4 / 15.2 / 20.0 |
| S3 level flip | 11,880 | 5,940 | 352 | 263 | 18,435 | 3.6 / 7.6 / 10.6 |

- Counts are exact: 2 debug and 1 info per order = 12,000 / 6,000 for 6,000 orders; warning and error follow their ~3% rates. Nothing was lost or duplicated.
- Level flip, checked in Splunk per 15 s bucket: with the config set to `warning` (sample 0.1), debug fell from ~3,000 to 160 and then 0 per bucket, info to 80 then 0, while warning and error kept arriving. After it returned to `debug`, full volume resumed within one bucket. No redeploy.
- At 100 orders/s nothing queued: delay of ~9 s average is the tunnel plus Splunk's indexing, not a backlog. Relay vs direct (8.4 vs 9.0 s) is within run-to-run noise; both ran over the same laptop tunnel, so this does not test the relay's round-trip advantage.
- S3's lower delay was not investigated. These are single runs, so treat differences of a few seconds as noise.
- Collector counters in S2: 18,415 accepted, 18,415 sent, 0 failed, queue 0.

Reproduce: `./setup_credentials.sh`, then `splunk-trial/up.sh`, then the `splunk_*_test.sh` scripts. `relay/docker-compose.demo.yml` makes the relay accept Splunk's self-signed certificate (demo only).

## Not tested / caveats

- The customer's own Splunk and network path. Tests 11-14 used one local Splunk Enterprise trial at 100 orders/s; its indexing limits are not theirs.
- The customer's timer-based batching design.
- A relay close to Eventing (same region). Round-trip savings are predicted, not measured.
- A single small cluster; numbers compare designs and are not forecasts for another environment.
- The relay's Collector config was validated and run locally, but option names should be re-checked for your version.

## Recommendations

1. Record every non-200 response and exception from the shipper (dead-letter collection); alert on it.
2. Write one log document per execution; drop debug, sample info, keep warn/error.
3. Size workers from a measurement, not a formula: run the shipper against an endpoint that answers 200 instantly,
   note calls/s per worker, then workers ≥ orders/s ÷ that number. On our path a worker did ~40 calls/s with a fast
   endpoint and ~11 calls/s with a 400 ms Splunk behind it (see "Full volume" below). Maximum is 64 per function.
4. Put a batching HEC relay between Eventing and Splunk; run two or more replicas.
5. Test the shipper against an endpoint that answers 200 instantly. If the ceiling disappears, the limit is in the path to Splunk.
6. Set a TTL on the logs collection, longer than the worst-case backlog.

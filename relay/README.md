# HEC relay for Eventing → Splunk

Put a small HEC-compatible relay between Capella Eventing and Splunk. Eventing keeps posting
Splunk-HEC-format events (the shipper only changes its URL); the relay acknowledges in about a
millisecond, then batches and forwards to Splunk over a few persistent connections.

Why: an Eventing worker is closed-loop: calls/s per worker ≈ 1 / call latency. Against a remote
Splunk (50-200 ms) a worker does 5-20 calls/s and many workers open many Splunk connections
("active connection limit reached"). Against a local relay a worker does hundreds of calls/s, and
Splunk sees only a few large batched requests.

## Files

| File | Purpose |
|---|---|
| `otel-collector-config.yaml` | Production relay: HEC in → batch → HEC out, persistent queue, retries |
| `otel-collector-null.yaml` | Decisive test: accept and discard (Splunk out of the picture) |
| `docker-compose.yml` | Runs either of the above |
| `mini_relay.py` | Reference relay in Python, same behaviour, for local testing |
| `hec_load.py` | Imitates N Eventing shipper workers (closed loop) |
| `run_relay_test.sh` | Local proof: direct-to-"Splunk" vs through the relay |

## 1. See the effect locally (no Docker, no Capella)

```bash
bash run_relay_test.sh          # LAT=50 LIMIT=8 DUR=8 to change the Splunk stand-in
```

Typical result on loopback: 1 worker goes from ~16 calls/s direct to ~1,000 via the relay; 16 workers
direct are mostly rejected by the connection limit, via the relay none are. Real networks add a
round trip to the relay, so expect a smaller (but still large) gain.

## 2. Decisive test in the customer's environment

1. Start the null relay (accepts and discards) where Eventing can reach it:
   `docker compose --profile null up -d relay-null`
2. Point the shipper's URL binding at `https://<relay-host>/services/collector/event`
   (same code, same token header).
3. Run the load test. Read the accepted rate from `http://<relay>:8888/metrics`
   (`otelcol_receiver_accepted_log_records`).

- Rate far above today's ~11K events/min → Splunk's per-call cost was the limit; use the real relay.
- Rate still stuck near the old ceiling → Eventing itself is the limit; ship from outside Eventing
  (SDK/DCP forwarder or Couchbase Kafka connector → Splunk Connect for Kafka).

## 3. Real relay

```bash
export SPLUNK_HEC_ENDPOINT='https://<splunk-host>:8088/services/collector'
export SPLUNK_HEC_TOKEN='<hec token>'
docker compose up -d relay
curl -s localhost:13133          # health
```

Run 2+ replicas behind a load balancer that terminates TLS. Restrict inbound to the Capella egress
IPs (or use PrivateLink/peering). Keep the Splunk token on the relay only, so Eventing never holds it
(use a separate relay-side secret if you want Eventing to authenticate to the relay).

Tuning: `batch.send_batch_size` (events per Splunk request), `sending_queue.num_consumers` (parallel
requests to Splunk; keep below its connection limit), `queue_size` and the file_storage volume
(buffer for Splunk outages).

Watch: `otelcol_receiver_accepted_log_records` vs `otelcol_exporter_sent_log_records` (should track
each other), `otelcol_exporter_queue_size` (growing = Splunk slower than inflow), failed-send counters.

## Caveats

- The Collector config could not be validated against a running image in the environment where it was
  written (no internet). Pin the image version, run `otelcol-contrib validate`, and check option names
  for your version; the receiver's accepted paths (`/services/collector/event`) should be confirmed.
- A relay removes the per-call latency and connection pressure; it does not make Eventing's own
  processing faster. Combine it with fewer/filtered logs and one doc per execution.
- The relay is at-least-once with a bounded disk queue. Size it for the longest Splunk outage you accept.

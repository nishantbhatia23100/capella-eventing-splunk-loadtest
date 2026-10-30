# Capella Eventing → Splunk HEC: load-test kit

Tools to reproduce and fix the "Eventing log shipping falls hours behind" problem on Couchbase Capella:
a function writes log documents, a second "shipper" function POSTs them to Splunk's HTTP Event Collector (HEC).

This repo contains the load generator, a mock Splunk HEC, Eventing function variants, scripts that deploy
and run them through the Capella Management API, a HEC relay (OpenTelemetry Collector) and the measured
results. See [RESULTS.md](RESULTS.md) for what was tested and what it showed.

Not an official Couchbase project: a reference kit. Use throwaway clusters.

## How it fits together

```
load_gen.py ──insert orders──▶ data.sales.orders ──▶ enrich_orders (business fn) ──▶ eventing-logs.eventing.logs
                                                                                             │
 mock_hec.py (Splunk stand-in)  ◀── public tunnel ◀── ship_logs (shipper fn, N workers) ◀────┘
   └─ reports delivery lag and end-to-end lag per 5 s           (optionally via relay/ → real HEC)
```

## Contents

| Path | Purpose |
|---|---|
| `functions/` | Eventing handlers: per-line logs (A), one doc per execution (C/D), filtered (E), shipper with failure records (F) |
| `templates/` | Function create/update payloads for the Capella Management API (v4) |
| `setup_capella.py` | Create buckets/scopes/collections, create/update/deploy/undeploy functions |
| `run_variant.sh` | One full cycle: undeploy, update code and workers, start mock, deploy, load, wait for drain, summarise |
| `matrix.sh` | The whole test matrix on two tunnels (direct and via relay) |
| `load_gen.py` | Rate-controlled order inserts (SDK or query-service mode) |
| `mock_hec.py` | Splunk HEC stand-in: service time, connection limit, gzip, lag reporting, CSV |
| `errs_report.py` | Counts and groups the shipper's failure records |
| `scrape_metrics.py`, `watch_counts.py`, `fn_status.py`, `cluster_info.py` | Node CPU/Eventing metrics, stage counts, function and cluster info |
| `summarize.py` | Compares run CSVs |
| `relay/` | HEC relay (OTel Collector) config, docker-compose, local demo and harness |
| `results/` | CSVs of the runs behind RESULTS.md |

## Requirements

Python 3 with `requests`; Docker (relay only); a Capella cluster with the Eventing service (Enterprise plan for the
Management API features used); a public HTTPS tunnel or endpoint that the cluster can reach and that
**does not rate-limit**. Free ngrok throttled Capella's traffic and invalidated early runs: see RESULTS.md.

## Configuration (nothing secret is stored in the repo)

Create a private file, e.g. `~/.loadtest-env` (mode 600), and `ids.env`:

```bash
# ~/.loadtest-env
export CAPELLA_API_KEY=...        # Management API key (add your IP to its allowlist)
export CB_USER=... CB_PASS=...    # database user (query + metrics access)
export CB_CONNSTR=couchbases://<cluster-host>
# ids.env
export ORG_ID=... PROJECT_ID=... CLUSTER_ID=...
```

Put the cluster's root certificate at `certs/cluster-root.pem` (Capella: cluster, Connect). Add your IP to the
cluster's allowed IPs. Then, with a tunnel to the mock on port 8088 and `HEC=https://<tunnel>/services/collector/event`:

```bash
python3 setup_capella.py --buckets          # keyspaces
# create the two functions once from templates/ (see setup_capella.py docstring), then:
. ~/.loadtest-env; . ./ids.env
HEC=... LATENCY=5 MAXCONNS=64 bash run_variant.sh F 200 60     # variant F, 200 orders/s for 60 s
python3 summarize.py run_F.csv
```

`bash matrix.sh` runs the full matrix. Keep the mock's `--max-conns` realistic for what you model.

## Safety

- Use a throwaway cluster; scripts create buckets and functions and insert tens of thousands of documents.
- Never commit `ids.env`, env files, certificates or tunnel URLs (`.gitignore` covers them).
- Rotate the API key and DB password after testing.

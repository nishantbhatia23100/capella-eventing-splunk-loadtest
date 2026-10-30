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
| `functions/` | Eventing handlers: per-line logs (A), one doc per execution (C/D), filtered (E), shipper with failure records (F), **log level controlled by a config document (G)** |
| `templates/` | Function create/update payloads for the Capella Management API (v4) |
| `setup_capella.py` | Create buckets/scopes/collections, create/update/deploy/undeploy functions |
| `run_variant.sh` | One full cycle: undeploy, update code and workers, start mock, deploy, load, wait for drain, summarise |
| `matrix.sh` | The whole test matrix on two tunnels (direct and via relay) |
| `load_gen.py` | Rate-controlled order inserts (SDK or query-service mode) |
| `mock_hec.py` | Splunk HEC stand-in: service time, connection limit, gzip, lag reporting, CSV |
| `errs_report.py` | Counts and groups the shipper's failure records |
| `scrape_metrics.py`, `watch_counts.py`, `fn_status.py`, `cluster_info.py` | Node CPU/Eventing metrics, stage counts, function and cluster info |
| `flip_config.py`, `test_config_flip.sh` | Change the log level at runtime and prove it (variant G) |
| `summarize.py` | Compares run CSVs |
| `relay/` | HEC relay (OTel Collector) config, docker-compose, local demo and harness |
| `results/` | CSVs of the runs behind RESULTS.md |

## Requirements

Python 3 with `requests`; Docker (relay only); a Capella cluster with the Eventing service (Enterprise plan for the
Management API features used); a public HTTPS tunnel or endpoint that the cluster can reach and that
**does not rate-limit**. Free ngrok throttled Capella's traffic and invalidated early runs: see RESULTS.md.

## Using this in your own Eventing functions

The functions in `functions/` are written for the test setup (an `orders` collection and made-up tier logic).
To adopt the fix, keep your own business logic and copy only the logging and shipping pattern.
Nothing else in the repo (`setup_capella.py`, `run_variant.sh`, `mock_hec.py`, `load_gen.py`, `splunk-trial/`) is needed in production.

### 1. Business function: write one log document per execution

Before (one document, one mutation, one later HEC call per log line):

```javascript
function OnUpdate(doc, meta) {
  logIt("info", "processing " + meta.id);
  // ... your logic ...
  logIt("error", "something failed");
}
function logIt(level, message) {
  logCollection["log::" + Date.now() + "::" + Math.floor(Math.random() * 1e7)] =
    { "level": level, "message": message, "t": Date.now() };
}
```

After (lines are collected in memory and written once; this is the pattern in `functions/C_D_enrich_orders_batched.js`):

```javascript
function OnUpdate(doc, meta) {
  var logs = [];
  function L(level, message) { logs.push({ t: Date.now(), level: level, message: message, meta_id: meta.id }); }
  try {
    L("info", "processing " + meta.id);
    // ... your logic ...
  } catch (e) {
    L("error", "unhandled exception for " + meta.id + ": " + String(e));
  } finally {
    if (logs.length) {
      logCollection["log::" + meta.id + "::" + Date.now() + "::" + Math.floor(Math.random() * 1e7)] =
        { "function": "my_function", "events": logs };
    }
  }
}
```

Eventing does not allow global variables (the function fails to compile), so keep every setting inside `OnUpdate`.
To control which levels are written, use `functions/G_enrich_orders_configurable.js` instead (section below).

### 2. Shipper function: use the batched shipper with failure records

Replace your shipper with `functions/F_ship_batched_dlq.js`. Before deploying it, set:

| What | Value |
|---|---|
| Source keyspace | the collection your business function writes logs to |
| Eventing metadata keyspace | your existing one |
| URL binding `splunkHEC` | your HEC event URL (or the relay URL), authentication **No Auth** |
| Bucket binding `errCol` (read and write) | a collection for failures, for example `shipper_errors` |
| `Authorization: Splunk <hec-token>` in the code | your real token. It is a plain string in the function, so restrict the token in Splunk (one index, no admin rights) |
| Workers | start with 2 to 4; more only helps if the path to Splunk is not the limit |
| Feed boundary | "From now" for a new deployment |

If you rename a binding or collection, change the matching name in the code.

### 3. Binding and keyspace checklist

| Function | Binding alias | Points to | Access |
|---|---|---|---|
| Business | `logCollection` | your log collection | read and write |
| Business (variant G only) | `cfg` | a config collection | read |
| Shipper | `splunkHEC` | HEC URL | No Auth |
| Shipper | `errCol` | a failure collection | read and write |

### 4. Check that it works

1. Run a small batch of real traffic and compare the number of documents in the log collection with the number of source documents: it should now be about one per execution.
2. Count events in Splunk for the same period, for example `index=couchbase | stats count by level`.
3. Count the documents in the failure collection. Any entry means HEC returned a non-200 status or the call failed; Eventing's own statistics do not show this.
4. If throughput stays flat as you add workers, the limit is between Eventing and Splunk; see [RESULTS.md](RESULTS.md) and `relay/`.

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

## Choosing which logs are shipped (variant G)

`functions/G_enrich_orders_configurable.js` reads a config document on every execution through a read-only
bucket binding `cfg` (collection `eventing-logs.eventing.config`), so the level can be changed with one write
and no redeploy:

```bash
python3 flip_config.py debug          # everything
python3 flip_config.py warning        # warnings and errors only
python3 flip_config.py info 0.1       # info sampled at 10%, plus warning/error
python3 flip_config.py temp-debug 30  # debug for 30 minutes, then back to the saved level
```

Document `loglevel::<function>` overrides `loglevel::default`; a missing document means `info` at 10%.
Filtering where the log is created is the main saving: it avoids the KV write, the DCP event, the dispatch and the
HTTP call. See RESULTS.md (test 10).

## Testing against a real Splunk

The mock removes Splunk's own limits, so the kit can also run against a real Splunk (a local Docker Splunk is enough):

```bash
export SPLUNK_AUTH=user:password SPLUNK_MGMT=https://localhost:8089 HEC_TOKEN=<hec token>
# tunnels/urls.env: HEC_SPLUNK=https://<tunnel>/services/collector/event   (tunnel origin = your HEC port)
bash splunk_direct_test.sh        # shipper -> tunnel -> Splunk HEC
bash splunk_relay_test.sh         # shipper -> tunnel -> OTel Collector relay -> Splunk HEC
bash splunk_level_flip_test.sh    # variant G: change the level mid-run, count what Splunk indexed
```

Events are counted from Splunk's REST API (`/services/data/indexes/<index>` `totalEventCount`), which needs no search
license. Things that cost time when setting this up:

- **Expired trial license:** an old Splunk container refuses all data searches ("license expired") while still indexing.
  Counting via REST (above) still works; renew or use a fresh instance for searches.
- **Low Docker disk:** Splunk stops searching/indexing below `minFreeSpace` (default 5000 MB). Free disk, or lower it
  for a throwaway test and restore it afterwards.
- **HEC scheme:** check whether HEC is HTTP or HTTPS after a container restart (`enableSSL`); a tunnel with the wrong
  origin scheme returns 502 for every call. For HTTPS with a self-signed certificate use `cloudflared --no-tls-verify`.
- **Splunk indexes slower than it accepts** (especially under amd64 emulation on Apple Silicon): HEC says 200 well
  before the event is countable. Judge delivery by the index count after it settles.

## Safety

- Use a throwaway cluster; scripts create buckets and functions and insert tens of thousands of documents.
- Never commit `ids.env`, env files, certificates or tunnel URLs (`.gitignore` covers them).
- Rotate the API key and DB password after testing.

#!/bin/bash
# Generic scenario runner: one business function, one or more shipper functions, one or more mock Splunks.
# Caller sources ~/.eventing-test-env, ids.env and tunnels/urls_fv.env first. Env:
#   TAG       run name (also the load_gen --run prefix)
#   PROFILE   load stages "rate:seconds,rate:seconds"          (default "200:60")
#   BIZ       business function file                           (default functions/C_D_enrich_orders_batched.js: ALL levels)
#   SHIPPERS  one per line: name|file|workers|hec_url|levels   (levels = comma list, empty = all)
#   MOCKS     space separated port:latency_ms:max_conns        (mock Splunk stand-ins, started here)
#   RELAY=1   restart the OTel Collector relay (port 8090) forwarding to mock RELAY_TO (default 19092)
#   OUTAGE    start_s:duration_s:mock_port  mock answers 503 during that window
#   METRICS=1 scrape cluster CPU and Eventing backlog during the run
#   DRAIN_MAX seconds to wait for delivery after the load (default 900)
set -u
cd "$(dirname "$0")"
PROFILE=${PROFILE:-200:60}; BIZ=${BIZ:-functions/C_D_enrich_orders_batched.js}; DRAIN_MAX=${DRAIN_MAX:-900}
CA="$PWD/certs/nishant-pr-root.pem"; LOAD_WORKERS=${LOAD_WORKERS:-8}; LOAD_BATCH=${LOAD_BATCH:-20}
say() { echo "[$(date +%H:%M:%S)] $*"; }
NAMES=$(echo "$SHIPPERS" | cut -d'|' -f1 | tr '\n' ' ')
ALLFN="enrich_orders ship_logs ship_debug"

say "scenario $TAG: profile=$PROFILE biz=$BIZ shippers: $(echo "$SHIPPERS" | tr '\n' ';')"
python3 errs_report.py --clear > /dev/null 2>&1
for f in $ALLFN; do python3 setup_capella.py --undeploy $f 2>&1 | grep -E "HTTP" | head -1; done
say "waiting 40s for undeploy"; sleep 40

out=$(python3 setup_capella.py --update-function templates/biz_template.json --name enrich_orders --code $BIZ 2>&1)
echo "$out" | grep -q "update HTTP 204" && say "updated enrich_orders" || { say "UPDATE FAILED enrich_orders"; echo "$out"; exit 5; }
echo "$SHIPPERS" | while IFS='|' read -r name file workers url levels; do
  [ -z "$name" ] && continue
  tmp=".ship_$name.js"; cp "$file" "$tmp"
  [ -n "${HEC_TOKEN:-}" ] && sed -i '' "s/<hec-token>/$HEC_TOKEN/" "$tmp"
  if [ -n "$levels" ]; then
    lv=$(echo "$levels" | sed -E 's/([a-z]+)/"\1"/g; s/,/, /g')
    sed -i '' -E "s/var WANT = \[[^]]*\];/var WANT = [$lv];/" "$tmp"
  fi
  out=$(python3 setup_capella.py --update-function templates/ship_template.json --name $name --code $tmp --hec-url "$url" --workers $workers 2>&1)
  if echo "$out" | grep -q "update HTTP 204"; then say "updated $name (workers $workers, levels ${levels:-all})"
  else
    out=$(python3 setup_capella.py --create-function templates/ship_template.json --name $name --code $tmp --hec-url "$url" --workers $workers 2>&1)
    echo "$out" | grep -q "create HTTP 2" && say "created $name (workers $workers, levels ${levels:-all})" || { say "CREATE FAILED $name"; echo "$out" | head -20; exit 5; }
  fi
done || exit 5

pkill -f mock_hec.py; sleep 1
for m in ${MOCKS:-}; do
  IFS=: read -r port lat conns <<< "$m"
  nohup python3 mock_hec.py --port $port --latency-ms $lat --jitter-ms 5 --max-conns $conns --report-sec 5 --csv run_${TAG}_p$port.csv > mock_${TAG}_p$port.log 2>&1 &
done
sleep 2
for m in ${MOCKS:-}; do port=${m%%:*}; curl -s --max-time 5 http://127.0.0.1:$port/stats > /dev/null && say "mock :$port up" || { say "mock :$port NOT up"; exit 3; }; done
MOCK_START=$(date +%s)

if [ -n "${RELAY:-}" ]; then
  ( cd relay && docker compose down -v > /dev/null 2>&1
    SPLUNK_HEC_ENDPOINT=http://host.docker.internal:${RELAY_TO:-19092}/services/collector SPLUNK_HEC_TOKEN=dummy RELAY_PORT=8090 \
      docker compose up -d relay > /dev/null 2>&1 )
  sleep 8; curl -s --max-time 5 localhost:13133 > /dev/null && say "relay up" || { say "relay NOT up"; exit 3; }
  ( : > relay_$TAG.csv; while true; do m=$(curl -s --max-time 3 localhost:8888/metrics); \
      echo "$(date +%s),$(echo "$m" | awk '/^otelcol_receiver_accepted_log_records/{a+=$2} /^otelcol_exporter_sent_log_records/{s+=$2} /^otelcol_exporter_queue_size/{q+=$2} END{print a+0","s+0","q+0}')" >> relay_$TAG.csv; sleep 5; done ) &
  RPOLL=$!
fi

for f in $NAMES; do python3 setup_capella.py --deploy $f 2>&1 | grep HTTP | head -1; done
python3 setup_capella.py --deploy enrich_orders 2>&1 | grep HTTP | head -1
say "waiting 60s for deployment to bootstrap"; sleep 60

TOTAL_LOAD=$(echo "$PROFILE" | tr ',' '\n' | awk -F: '{s+=$2} END{print s}')
if [ -n "${METRICS:-}" ]; then python3 scrape_metrics.py 5 $((TOTAL_LOAD + DRAIN_MAX + 120)) metrics_$TAG.jsonl > /dev/null 2>&1 & MPID=$!; fi
LOAD_START=$(date +%s); i=0
if [ -n "${OUTAGE:-}" ]; then   # start_s:duration_s:mock_port : the mock returns 503 for the window
  IFS=: read -r o_s o_d o_p <<< "$OUTAGE"
  ( sleep $o_s; say "OUTAGE start (mock :$o_p returns 503 for ${o_d}s)"; curl -s "http://127.0.0.1:$o_p/ctl?down=1" > /dev/null
    sleep $o_d; curl -s "http://127.0.0.1:$o_p/ctl?down=0" > /dev/null; say "OUTAGE end" ) &
fi
for stage in $(echo "$PROFILE" | tr ',' ' '); do
  i=$((i+1)); r=${stage%%:*}; d=${stage##*:}
  say "load stage $i: ${r}/s for ${d}s"
  python3 load_gen.py --via-query --ca-cert "$CA" --rate $r --duration $d --workers $LOAD_WORKERS --batch $LOAD_BATCH --run ${TAG}$i > load_${TAG}_$i.log 2>&1
  tail -1 load_${TAG}_$i.log
  grep -q "errors=0 achieved" load_${TAG}_$i.log || say "WARNING: load stage $i had errors or missed its rate"
done
LOAD_END=$(date +%s)

get_events() { local t=0; for m in ${MOCKS:-}; do n=$(curl -s --max-time 5 http://127.0.0.1:${m%%:*}/stats | python3 -c "import sys,json;print(json.load(sys.stdin)['events'])" 2>/dev/null || echo 0); t=$((t+n)); done; echo $t; }
say "waiting for delivery (idle = no new events for 45s, max ${DRAIN_MAX}s)"
last=-1; idle=0; waited=0; timeout=0
while :; do
  sleep 10; waited=$((waited+10)); cur=$(get_events)
  if [ "$cur" = "$last" ] && [ "$cur" != "0" ]; then idle=$((idle+10)); else idle=0; fi; last=$cur
  [ $((waited % 60)) -eq 0 ] && say "events=$cur"
  [ $idle -ge 45 ] && break
  [ $waited -ge $((DRAIN_MAX)) ] && { timeout=1; say "DRAIN TIMEOUT after ${DRAIN_MAX}s"; break; }
done
DRAIN_END=$(date +%s); say "delivered so far: $last events (waited ${waited}s after load)"

# expected events: wait until the business function's log count is stable
prev=""; for _ in 1 2 3 4 5 6 7 8; do cur=$(python3 expected_events.py $TAG); [ "$cur" = "$prev" ] && break; prev=$cur; sleep 10; done
echo "$cur" > expected_$TAG.json; say "expected $cur"
printf 'MOCK_START=%s\nLOAD_START=%s\nLOAD_END=%s\nDRAIN_END=%s\nDRAIN_TIMEOUT=%s\n' $MOCK_START $LOAD_START $LOAD_END $DRAIN_END $timeout > timing_$TAG.env

for f in $ALLFN; do python3 setup_capella.py --undeploy $f 2>&1 | grep HTTP | head -1; done
python3 errs_report.py > errs_$TAG.txt 2>&1
[ -n "${MPID:-}" ] && kill $MPID 2>/dev/null
[ -n "${RPOLL:-}" ] && kill $RPOLL 2>/dev/null
pkill -f mock_hec.py
python3 scenario_report.py $TAG "$SHIPPERS" "${MOCKS:-}" | tee -a scenario_results.txt
say "scenario $TAG done"

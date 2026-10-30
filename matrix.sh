#!/bin/bash
# Full matrix on a non-throttling tunnel (cloudflared). 200 orders/s for 60 s per run.
cd "$(dirname "$0")"
. "${ENV_FILE:-$HOME/.loadtest-env}"; . ./ids.env; . tunnels/urls.env
pkill -f mock_hec.py; pkill -f run_variant.sh
(cd relay && docker compose down -v >/dev/null 2>&1)

run_one() {   # tag variant workers mock_latency_ms hec_url mock_port
  local tag=$1 var=$2 w=$3 lat=$4 hec=$5 mp=$6
  echo "[$(date +%T)] START $tag (variant $var, workers $w, mock ${lat}ms, port $mp)" >> matrix.log
  python3 errs_report.py --clear > /dev/null 2>&1
  HEC=$hec MOCKPORT=$mp TAG=$tag LATENCY=$lat MAXCONNS=64 WORKERS_OVERRIDE=$w bash run_variant.sh $var 200 60 > run_$tag.log 2>&1
  python3 errs_report.py > errs_$tag.txt 2>&1
  echo "[$(date +%T)] END   $tag" >> matrix.log
}

: > matrix.log
# --- direct to the mock (fast, 5 ms) : does worker count scale?
run_one X1 F 1 5  "$HEC_DIRECT" 8088
run_one X2 F 2 5  "$HEC_DIRECT" 8088
run_one X4 F 4 5  "$HEC_DIRECT" 8088
run_one X8 F 8 5  "$HEC_DIRECT" 8088
# --- direct to a slow Splunk stand-in (50 ms): effect of call latency
run_one Y4 F 4 50 "$HEC_DIRECT" 8088
# --- the customer's shape: per-line docs, many workers
run_one P8 B 8 5  "$HEC_DIRECT" 8088
# --- through the relay (real Collector) to a 50 ms Splunk stand-in
(cd relay && SPLUNK_HEC_ENDPOINT=http://host.docker.internal:18088/services/collector SPLUNK_HEC_TOKEN=dummy RELAY_PORT=8089 docker compose up -d relay >> ../matrix.log 2>&1)
sleep 8
run_one Z1 F 1 50 "$HEC_RELAY" 18088
run_one Z4 F 4 50 "$HEC_RELAY" 18088
echo "[$(date +%T)] ALL DONE" >> matrix.log

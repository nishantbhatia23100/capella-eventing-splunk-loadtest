#!/bin/bash
# Full cycle for one variant. Needs CAPELLA_API_KEY, CB_*, ORG_ID, PROJECT_ID, CLUSTER_ID in the environment.
#   bash run_variant.sh B|C|D   [rate] [duration]
set -u
V=${1:?variant B|C|D}; RATE=${2:-200}; DUR=${3:-60}
TAG=${TAG:-$V}; MAXCONNS=${MAXCONNS:-8}; MOCKPORT=${MOCKPORT:-8088}; MOCKARGS=${MOCKARGS:-}
HEC=${HEC:?set HEC to the public URL of your HEC endpoint or relay, ending in /services/collector/event}
CA="$PWD/certs/cluster-root.pem"
case $V in
  B) BIZ=functions/A_enrich_orders.js;          SHIP=functions/A_C_ship_per_doc.js; W=8;;
  C) BIZ=functions/C_D_enrich_orders_batched.js; SHIP=functions/A_C_ship_per_doc.js; W=1;;
  D) BIZ=functions/C_D_enrich_orders_batched.js; SHIP=functions/D_ship_batched.js;    W=4;;
  F) BIZ=functions/C_D_enrich_orders_batched.js; SHIP=functions/F_ship_batched_dlq.js; W=4;;
  E) BIZ=functions/E_enrich_orders_filtered.js;  SHIP=functions/D_ship_batched.js;    W=1;;
  *) echo "unknown variant"; exit 2;;
esac
W=${WORKERS_OVERRIDE:-$W}
say() { echo "[$(date +%H:%M:%S)] $*"; }

say "variant $V (tag $TAG, mock max-conns $MAXCONNS): biz=$BIZ ship=$SHIP shipper workers=$W"
python3 setup_capella.py --undeploy enrich_orders | tail -2
python3 setup_capella.py --undeploy ship_logs | tail -2
say "waiting 40s for undeploy"; sleep 40
for spec in "biz_template.json enrich_orders $BIZ" "ship_template.json ship_logs $SHIP"; do
  set -- $spec
  extra=""; [ "$2" = "ship_logs" ] && extra="--hec-url $HEC --workers $W"
  out=$(python3 setup_capella.py --update-function templates/$1 --name $2 --code $3 $extra 2>&1)
  if echo "$out" | grep -q "update HTTP 204"; then say "updated $2"; else say "UPDATE FAILED for $2, aborting"; echo "$out"; exit 5; fi
done

pkill -f "mock_hec.py" ; sleep 1
nohup python3 mock_hec.py --port $MOCKPORT --latency-ms ${LATENCY:-50} --max-conns $MAXCONNS $MOCKARGS --csv run_$TAG.csv > mock_$TAG.log 2>&1 &
sleep 2; curl -s --max-time 5 http://127.0.0.1:$MOCKPORT/stats >/dev/null && say "mock up" || { say "mock NOT up"; exit 3; }

python3 setup_capella.py --deploy ship_logs | tail -2
python3 setup_capella.py --deploy enrich_orders | tail -2
say "waiting 60s for deployment to bootstrap"; sleep 60

say "load: ${RATE}/s for ${DUR}s"
python3 load_gen.py --via-query --ca-cert "$CA" --rate $RATE --duration $DUR --workers 8 > load_$TAG.log 2>&1
tail -3 load_$TAG.log
if ! grep -q "errors=0 achieved" load_$TAG.log; then say "LOAD FAILED, aborting"; python3 setup_capella.py --undeploy enrich_orders | tail -1; python3 setup_capella.py --undeploy ship_logs | tail -1; exit 4; fi

say "waiting for drain (idle = no new events for 45s)"
last=-1; idle=0; waited=0
while [ $waited -lt 2700 ]; do
  sleep 10; waited=$((waited+10))
  cur=$(curl -s --max-time 5 http://127.0.0.1:$MOCKPORT/stats | python3 -c "import sys,json;print(json.load(sys.stdin)['events'])" 2>/dev/null || echo -1)
  if [ "$cur" = "$last" ] && [ "$cur" != "0" ] && [ "$cur" != "-1" ]; then idle=$((idle+10)); else idle=0; fi
  last=$cur
  [ $((waited % 60)) -eq 0 ] && say "events=$cur"
  [ $idle -ge 45 ] && break
done
say "drained: events=$last waited=${waited}s"
sleep 6
python3 summarize.py run_$TAG.csv
python3 setup_capella.py --undeploy enrich_orders | tail -1
python3 setup_capella.py --undeploy ship_logs | tail -1
say "variant $V done"

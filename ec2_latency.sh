#!/bin/bash
# Per-call latency sweep: how many events/s does each design move when the Splunk path is slow?
# Runs on the load host in the same region as the cluster. Mock Splunk with a fixed service time stands in for a far/slow HEC.
#   bash ec2_latency.sh                       run the whole list below
#   LIST="L1 L3" bash ec2_latency.sh          run selected tags
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env; unset HEC_TOKEN
IP=${LG_IP:?set LG_IP}
export DRAIN_MAX=${DRAIN_MAX:-240} METRICS=1 CLEAR_LOGS=1 EXPECT_ALL=1
CUST_BIZ=functions/J_customer_enrich_orders.js; CUST_SHIP=functions/J_customer_ship_logs.js
NEW_BIZ=functions/C_D_enrich_orders_batched.js; NEW_SHIP=functions/F_ship_batched_dlq.js
# tag | biz | shipper | workers | mock latency ms | relay(0/1) | profile
RUNS="
L1|$CUST_BIZ|$CUST_SHIP|1|100|0|150:75
L2|$CUST_BIZ|$CUST_SHIP|8|100|0|150:75
L3|$CUST_BIZ|$CUST_SHIP|1|100|1|150:75
L4|$NEW_BIZ|$NEW_SHIP|1|100|0|150:75
L5|$NEW_BIZ|$NEW_SHIP|1|100|1|150:75
L6|$CUST_BIZ|$CUST_SHIP|1|25|0|150:75
L7|$CUST_BIZ|$CUST_SHIP|1|50|0|150:75
"
echo "$RUNS" | while IFS='|' read -r tag biz ship w lat relay profile; do
  [ -z "$tag" ] && continue
  [ -n "${LIST:-}" ] && ! echo " $LIST " | grep -q " $tag " && continue
  export TAG=$tag BIZ=$biz PROFILE=$profile
  if [ "$relay" = 1 ]; then
    export RELAY=1 RELAY_TO=19092 MOCKS="19092:$lat:256"
    url="http://$IP:8090/services/collector/event"
  else
    unset RELAY RELAY_TO; export MOCKS="18090:$lat:256"
    url="http://$IP:18090/services/collector/event"
  fi
  export SHIPPERS="ship_logs|$ship|$w|$url|"
  bash run_scenario.sh > run_$tag.out 2>&1
  echo "=== $tag: biz=$(basename $biz) workers=$w latency=${lat}ms relay=$relay" >> latency_report.txt
  tail -8 run_$tag.out | grep -E "expected|mock|relay|cluster" >> latency_report.txt
done
echo LATENCY_DONE >> latency_report.txt

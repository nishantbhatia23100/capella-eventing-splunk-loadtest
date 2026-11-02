#!/bin/bash
# What the Splunk-side errors seen in the field do to each design:
#   503 "Server is busy, active connection limit reached" (HEC at its connection limit)
#   504 Gateway Time-out (a proxy in front of Splunk giving up on a slow upstream)
# Each run: customer's code vs the new design (failure records), direct vs through a relay in the same region.
#   bash ec2_errors.sh            LIST="E1 E4" to run some
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env; unset HEC_TOKEN
IP=${LG_IP:?set LG_IP}
# wait for any sweep still running (same function names, same cluster)
while pgrep -f "[e]c2_latency.sh" > /dev/null; do sleep 10; done
export DRAIN_MAX=${DRAIN_MAX:-240} METRICS=1 CLEAR_LOGS=1 EXPECT_ALL=1
CUST_BIZ=functions/J_customer_enrich_orders.js; CUST_SHIP=functions/J_customer_ship_logs.js
NEW_BIZ=functions/C_D_enrich_orders_batched.js; NEW_SHIP=functions/F_ship_batched_dlq.js
# tag | biz | shipper | workers | mock "latency:max_conns[:p504:gw_ms]" | relay | profile
RUNS="
E1|$CUST_BIZ|$CUST_SHIP|16|5:8|0|150:75
E2|$NEW_BIZ|$NEW_SHIP|16|5:8|0|150:75
E3|$NEW_BIZ|$NEW_SHIP|16|5:8|1|150:75
E4|$CUST_BIZ|$CUST_SHIP|8|10:64:0.02:15000|0|150:75
E5|$NEW_BIZ|$NEW_SHIP|8|10:64:0.02:15000|0|150:75
E6|$CUST_BIZ|$CUST_SHIP|8|10:64:0.02:15000|1|150:75
"
echo "$RUNS" | while IFS='|' read -r tag biz ship w spec relay profile; do
  [ -z "$tag" ] && continue
  [ -n "${LIST:-}" ] && ! echo " $LIST " | grep -q " $tag " && continue
  export TAG=$tag BIZ=$biz PROFILE=$profile
  if [ "$relay" = 1 ]; then
    export RELAY=1 RELAY_TO=19092 MOCKS="19092:$spec"; url="http://$IP:8090/services/collector/event"
  else
    unset RELAY RELAY_TO; export MOCKS="18090:$spec"; url="http://$IP:18090/services/collector/event"
  fi
  export SHIPPERS="ship_logs|$ship|$w|$url|"
  bash run_scenario.sh > run_$tag.out 2>&1
  port=$([ "$relay" = 1 ] && echo 19092 || echo 18090)
  { echo "=== $tag: biz=$(basename $biz) workers=$w mock=$spec relay=$relay"
    tail -8 run_$tag.out | grep -E "expected|mock|relay|cluster"
    echo "mock final stats: $(curl -s localhost:$port/stats | head -c 300)"
    python3 errs_report.py 2>&1 | head -4; } >> errors_report.txt
done
echo ERRORS_DONE >> errors_report.txt

#!/bin/bash
# Customer's exact functions (functions/J_*) against a fast mock endpoint, stepped load, several worker counts.
#   bash ec2_baseline.sh "1 4 16"
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env; unset HEC_TOKEN
IP=${LG_IP:?set LG_IP}
export PROFILE=${PROFILE:-"20:60,40:60,60:60,100:60,150:60,250:60,400:60"} DRAIN_MAX=${DRAIN_MAX:-300} METRICS=1 CLEAR_LOGS=1 EXPECT_ALL=1
export BIZ=functions/J_customer_enrich_orders.js MOCKS="18090:5:128"
for w in ${1:-1 4 16}; do
  export TAG=J_w$w
  export SHIPPERS="ship_logs|functions/J_customer_ship_logs.js|$w|http://$IP:18090/services/collector/event|"
  bash run_scenario.sh > run_$TAG.out 2>&1
  python3 scenario_report.py $TAG >> ladder_report.txt 2>&1
done
echo ALL_DONE >> ladder_report.txt

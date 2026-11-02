#!/bin/bash
# Customer's exact functions against the REAL Splunk, stepped load.   bash ec2_splunk_baseline.sh "1 4"
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env
export PROFILE=${PROFILE:-"20:60,40:60,60:60,100:60,150:60,250:60,400:60"} DRAIN_MAX=${DRAIN_MAX:-600} METRICS=1 CLEAR_LOGS=1 EXPECT_ALL=1
export SPLUNK_COUNT=1 NO_TLS_VERIFY=1 MOCKS=""
export BIZ=functions/J_customer_enrich_orders.js
for w in ${1:-1 4}; do
  export TAG=JS_w$w
  export SHIPPERS="ship_logs|functions/J_customer_ship_logs.js|$w|http://${SPLUNK_IP:?set SPLUNK_IP}:8088/services/collector/event|"
  bash run_scenario.sh > run_$TAG.out 2>&1
done
echo SPLUNK_BASELINE_DONE >> ladder_report.txt

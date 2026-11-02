#!/bin/bash
# New design (one log document per execution + batched shipper with failure records) against the REAL Splunk, stepped load.
#   bash ec2_newdesign.sh "8 16 32"          PROFILE / SPLUNK_IP / DRAIN_MAX can be overridden
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env
export PROFILE=${PROFILE:-"100:60,300:60,600:60,1000:60,1500:60"} DRAIN_MAX=${DRAIN_MAX:-600} METRICS=1 CLEAR_LOGS=1 EXPECT_ALL=1
export SPLUNK_COUNT=1 NO_TLS_VERIFY=1 MOCKS=""
export BIZ=functions/C_D_enrich_orders_batched.js
for w in ${1:-8 16 32}; do
  export TAG=NS_w$w
  export SHIPPERS="ship_logs|functions/F_ship_batched_dlq.js|$w|http://${SPLUNK_IP:?set SPLUNK_IP}:8088/services/collector/event|"
  bash run_scenario.sh > run_$TAG.out 2>&1
done
echo NEWDESIGN_DONE >> ladder_report.txt

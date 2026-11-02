#!/bin/bash
# Push the new design to its limit against the REAL Splunk, direct and through the in-region relay.
#   bash ec2_push.sh            LIST="P1" to run one
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env
SIP=${SPLUNK_IP:?set SPLUNK_IP}; IP=${LG_IP:?set LG_IP}
export PROFILE=${PROFILE:-"300:60,600:60,1000:60,1500:60,2000:60"} DRAIN_MAX=${DRAIN_MAX:-420} METRICS=1 CLEAR_LOGS=1 EXPECT_ALL=1
export SPLUNK_COUNT=1 NO_TLS_VERIFY=1 MOCKS="" BIZ=functions/C_D_enrich_orders_batched.js
W=${W:-16}
for t in P1 P2; do
  [ -n "${LIST:-}" ] && ! echo " $LIST " | grep -q " $t " && continue
  export TAG=$t
  if [ "$t" = P2 ]; then
    export RELAY=1 RELAY_ENDPOINT="http://$SIP:8088/services/collector" RELAY_REAL_TOKEN="$HEC_TOKEN"
    url="http://$IP:8090/services/collector/event"
  else
    unset RELAY RELAY_ENDPOINT RELAY_REAL_TOKEN; url="http://$SIP:8088/services/collector/event"
  fi
  export SHIPPERS="ship_logs|functions/F_ship_batched_dlq.js|$W|$url|"
  bash run_scenario.sh > run_$t.out 2>&1
  { echo "=== $t: new design, $W workers, $([ "$t" = P2 ] && echo via relay || echo direct) to real Splunk"
    grep -E "load stage|done: sent|DRAIN|delivered so far|expected" run_$t.out | cut -c1-200
    python3 errs_report.py 2>&1 | head -3; } >> push_report.txt
done
echo PUSH_DONE >> push_report.txt

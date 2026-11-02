#!/bin/bash
# Outage and soak against the REAL Splunk (new design: one doc per execution, batched shipper with failure records).
#   O1  Splunk HEC refused for 5 min under steady load, shipper -> Splunk directly
#   O2  same outage, shipper -> in-region relay -> Splunk
#   SK  soak: steady load for SOAK_S seconds through the relay
#   bash ec2_outage_soak.sh          LIST="O2" to run some
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env
SIP=${SPLUNK_IP:?set SPLUNK_IP}; IP=${LG_IP:?set LG_IP}
export METRICS=1 CLEAR_LOGS=1 EXPECT_ALL=1 SPLUNK_COUNT=1 NO_TLS_VERIFY=1 MOCKS="" BIZ=functions/C_D_enrich_orders_batched.js
W=${W:-16}; SOAK_S=${SOAK_S:-1800}; SOAK_RATE=${SOAK_RATE:-400}
for t in O1 O2 SK; do
  [ -n "${LIST:-}" ] && ! echo " $LIST " | grep -q " $t " && continue
  export TAG=$t DRAIN_MAX=900
  case $t in
    O1) export PROFILE="300:600" SPLUNK_OUTAGE="180:300"; unset RELAY RELAY_ENDPOINT RELAY_REAL_TOKEN; url="http://$SIP:8088/services/collector/event";;
    O2) export PROFILE="300:600" SPLUNK_OUTAGE="180:300" RELAY=1 RELAY_ENDPOINT="http://$SIP:8088/services/collector" RELAY_REAL_TOKEN="$HEC_TOKEN"; url="http://$IP:8090/services/collector/event";;
    SK) export PROFILE="$SOAK_RATE:$SOAK_S"; unset SPLUNK_OUTAGE; export RELAY=1 RELAY_ENDPOINT="http://$SIP:8088/services/collector" RELAY_REAL_TOKEN="$HEC_TOKEN"; url="http://$IP:8090/services/collector/event";;
  esac
  export SHIPPERS="ship_logs|functions/F_ship_batched_dlq.js|$W|$url|"
  bash run_scenario.sh > run_$t.out 2>&1
  { echo "=== $t ($W workers, profile $PROFILE, outage ${SPLUNK_OUTAGE:-none}, $([ -n "${RELAY:-}" ] && echo relay || echo direct))"
    grep -E "OUTAGE|DRAIN|delivered so far|expected \{" run_$t.out | cut -c1-200
    grep -E "cluster CPU" run_$t.out | cut -c1-200
    python3 errs_report.py 2>&1 | head -4 | cut -c1-300
    [ -f relay_$t.csv ] && awk -F, 'NR>1{if($4>m)m=$4; last=$0} END{print "relay: peak queue batches",m+0,"| last sample (ts,accepted,sent,queue):",last}' relay_$t.csv
  } >> outage_soak_report.txt
  python3 splunk_verify.py $t >> outage_soak_report.txt 2>&1
done
echo OUTAGE_SOAK_DONE >> outage_soak_report.txt

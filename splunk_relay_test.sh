#!/bin/bash
# Real Splunk via the relay: shipper -> tunnel -> OTel Collector -> Splunk HEC (see relay/otel-collector-selfsigned-demo.yaml).
# Needs: ~/.loadtest-env (Capella + DB credentials), ids.env, tunnels/urls.env with HEC_RELAY_SPLUNK, and for Splunk:
#   export SPLUNK_AUTH=user:password  SPLUNK_MGMT=https://<splunk>:8089  HEC_TOKEN=<hec token>
cd "$(dirname "$0")"
. "${ENV_FILE:-$HOME/.loadtest-env}"; . ./ids.env; . tunnels/urls.env
export REAL_SPLUNK=1 SPLUNK_MGMT="${SPLUNK_MGMT:-https://localhost:8089}"
: "${SPLUNK_AUTH:?set SPLUNK_AUTH=user:password}" "${HEC_TOKEN:?set HEC_TOKEN}"
pkill -f run_variant.sh
python3 errs_report.py --clear > /dev/null 2>&1
HEC=$HEC_RELAY_SPLUNK TAG=S2 WORKERS_OVERRIDE=2 bash run_variant.sh F 100 60 > run_S2.log 2>&1
python3 errs_report.py > errs_S2.txt 2>&1
echo "S2 DONE" >> run_S2.log

#!/bin/bash
# Real Splunk, direct: shipper (2 workers) -> tunnel -> Splunk HEC, 100 orders/s for 60 s.
# Needs: ~/.loadtest-env (Capella + DB credentials), ids.env, tunnels/urls.env with HEC_SPLUNK, and for Splunk:
#   export SPLUNK_AUTH=user:password  SPLUNK_MGMT=https://<splunk>:8089  HEC_TOKEN=<hec token>
cd "$(dirname "$0")"
. "${ENV_FILE:-$HOME/.loadtest-env}"; . ./ids.env; . tunnels/urls.env
export REAL_SPLUNK=1 SPLUNK_MGMT="${SPLUNK_MGMT:-https://localhost:8089}"
: "${SPLUNK_AUTH:?set SPLUNK_AUTH=user:password}" "${HEC_TOKEN:?set HEC_TOKEN}"
pkill -f run_variant.sh
python3 errs_report.py --clear > /dev/null 2>&1
HEC=$HEC_SPLUNK TAG=S1 WORKERS_OVERRIDE=2 bash run_variant.sh F 100 60 > run_S1.log 2>&1
python3 errs_report.py > errs_S1.txt 2>&1
echo "S1 DONE" >> run_S1.log

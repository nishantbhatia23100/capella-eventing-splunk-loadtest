#!/bin/bash
# Runtime log level against real Splunk (needs SPLUNK_AUTH, HEC_TOKEN, SPLUNK_MGMT): debug -> warning (+30 s) -> debug (+60 s), counted from Splunk's side.
cd "$(dirname "$0")"
. "${ENV_FILE:-$HOME/.loadtest-env}"; . ./ids.env; . tunnels/urls.env
pkill -f mock_hec.py; pkill -f run_variant.sh
python3 setup_capella.py --buckets > /dev/null 2>&1; sleep 5
python3 flip_config.py debug > cfgtest_s3.log 2>&1
python3 errs_report.py --clear > /dev/null 2>&1
export REAL_SPLUNK=1 SPLUNK_MGMT="${SPLUNK_MGMT:-https://localhost:8089}"
: "${SPLUNK_AUTH:?set SPLUNK_AUTH=user:password}" "${HEC_TOKEN:?set HEC_TOKEN}"
HEC=$HEC_SPLUNK TAG=S3 bash run_variant.sh G 100 90 > run_S3.log 2>&1 &
RUNNER=$!
until grep -q "load:" run_S3.log 2>/dev/null || ! kill -0 $RUNNER 2>/dev/null; do sleep 1; done
T0=$(date +%s); echo "load started $(date +%T) epoch=$T0" >> cfgtest_s3.log
sleep 30; python3 flip_config.py warning >> cfgtest_s3.log 2>&1; echo "flip warning at +$(( $(date +%s)-T0 ))s" >> cfgtest_s3.log
sleep 30; python3 flip_config.py debug   >> cfgtest_s3.log 2>&1; echo "flip debug   at +$(( $(date +%s)-T0 ))s" >> cfgtest_s3.log
wait $RUNNER
python3 errs_report.py > errs_S3.txt 2>&1
echo "S3 DONE" >> cfgtest_s3.log

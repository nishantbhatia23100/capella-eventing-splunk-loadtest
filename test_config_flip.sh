#!/bin/bash
# Prove the log level can be changed at runtime: debug -> warning (+30 s) -> debug (+60 s), no redeploy.
cd "$(dirname "$0")"
. "${ENV_FILE:-$HOME/.loadtest-env}"; . ./ids.env; . tunnels/urls.env
RATE=${RATE:-100}; DUR=${DUR:-90}
pkill -f mock_hec.py; pkill -f run_variant.sh
python3 setup_capella.py --buckets > cfgtest_setup.log 2>&1; sleep 20       # creates the config collection if missing
python3 flip_config.py debug > cfgtest.log 2>&1
python3 errs_report.py --clear > /dev/null 2>&1
HEC=$HEC_DIRECT MOCKPORT=8088 TAG=G LATENCY=5 MAXCONNS=64 bash run_variant.sh G $RATE $DUR > run_G.log 2>&1 &
RUNNER=$!
until grep -q "load:" run_G.log 2>/dev/null || ! kill -0 $RUNNER 2>/dev/null; do sleep 1; done
T0=$(date +%s); echo "load started $(date +%T)" >> cfgtest.log
sleep 30; python3 flip_config.py warning >> cfgtest.log 2>&1; echo "flip warning at +$(( $(date +%s)-T0 ))s" >> cfgtest.log
sleep 30; python3 flip_config.py debug   >> cfgtest.log 2>&1; echo "flip debug   at +$(( $(date +%s)-T0 ))s" >> cfgtest.log
wait $RUNNER
python3 errs_report.py > errs_G.txt 2>&1
echo "TEST DONE" >> cfgtest.log

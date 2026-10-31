#!/bin/bash
# Round 3a: priority isolation with EQUAL total workers (8) and a debug path that cannot keep up (400 ms, 100 orders/s).
cd "$(dirname "$0")"; . tunnels/urls_fv.env
F=functions/F_ship_batched_dlq.js; H=functions/H_ship_levels.js
run() { local tag=$1; shift; echo "[$(date +%T)] START $tag" >> fv_matrix3.log; env TAG=$tag "$@" ./fv_run.sh > run_$tag.log 2>&1; echo "[$(date +%T)] END   $tag" >> fv_matrix3.log; }
: > fv_matrix3.log
run I0c PROFILE=100:60 SHIPPERS="ship_logs|$F|8|$HEC_M2|" MOCKS="19091:400:1024"
run I1c PROFILE=100:60 SHIPPERS="ship_logs|$H|6|$HEC_M1|info,warning,error
ship_debug|$H|2|$HEC_M2|debug" MOCKS="18090:5:1024 19091:400:1024"
echo "[$(date +%T)] ALL DONE" >> fv_matrix3.log

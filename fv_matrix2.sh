#!/bin/bash
# Round 2 (all levels kept): outage handling, priority isolation retuned to saturate, slow-Splunk capacity limit, relay at 800 orders/s.
cd "$(dirname "$0")"; . tunnels/urls_fv.env
F=functions/F_ship_batched_dlq.js; H=functions/H_ship_levels.js
run() { local tag=$1; shift; echo "[$(date +%T)] START $tag" >> fv_matrix2.log; env TAG=$tag "$@" ./fv_run.sh > run_$tag.log 2>&1; echo "[$(date +%T)] END   $tag" >> fv_matrix2.log; }
: > fv_matrix2.log
# --- 1. Splunk outage of 40 s in the middle of a 120 s run (200 orders/s)
run OD PROFILE=200:120 OUTAGE=30:40:18090 SHIPPERS="ship_logs|$F|8|$HEC_M1|" MOCKS="18090:5:1024" METRICS=1
run OR PROFILE=200:120 OUTAGE=30:40:19092 RELAY=1 RELAY_TO=19092 SHIPPERS="ship_logs|$F|8|$HEC_RELAY|" MOCKS="19092:5:1024" METRICS=1
# --- 2. priority isolation, retuned so the slow path really saturates (equal total workers: 12)
run I0b PROFILE=100:60 SHIPPERS="ship_logs|$F|12|$HEC_M2|" MOCKS="19091:400:1024"
run I1b PROFILE=100:60 SHIPPERS="ship_logs|$H|8|$HEC_M1|info,warning,error
ship_debug|$H|4|$HEC_M2|debug" MOCKS="18090:5:1024 19091:400:1024"
# --- 3. where direct delivery to a 400 ms Splunk runs out of workers (200 orders/s)
run L400w16 PROFILE=200:60 SHIPPERS="ship_logs|$F|16|$HEC_M1|" MOCKS="18090:400:1024" METRICS=1
run L400w32 PROFILE=200:60 SHIPPERS="ship_logs|$F|32|$HEC_M1|" MOCKS="18090:400:1024" METRICS=1
# --- 4. relay at 800 orders/s with a 400 ms Splunk behind it
run R800w32 PROFILE=800:60 LOAD_WORKERS=16 LOAD_BATCH=50 RELAY=1 RELAY_TO=19092 SHIPPERS="ship_logs|$F|32|$HEC_RELAY|" MOCKS="19092:400:1024" METRICS=1
echo "[$(date +%T)] ALL DONE" >> fv_matrix2.log

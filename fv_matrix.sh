#!/bin/bash
# Full-volume matrix: every log level is kept in every run. Sequential; results in scenario_results.csv / scenario_results.txt.
cd "$(dirname "$0")"; . tunnels/urls_fv.env
F=functions/F_ship_batched_dlq.js; H=functions/H_ship_levels.js
run() { # tag
  local tag=$1; shift; echo "[$(date +%T)] START $tag" >> fv_matrix.log
  env TAG=$tag "$@" ./fv_run.sh > run_$tag.log 2>&1
  echo "[$(date +%T)] END   $tag" >> fv_matrix.log
}
: > fv_matrix.log
# --- 1. isolation: does a slow debug path delay errors? (100 orders/s, Splunk stand-in for debug = 400 ms)
run I0 PROFILE=100:60 SHIPPERS="ship_logs|$F|16|$HEC_M2|" MOCKS="19091:400:1024"
run I1 PROFILE=100:60 SHIPPERS="ship_logs|$H|8|$HEC_M1|info,warning,error
ship_debug|$H|16|$HEC_M2|debug" MOCKS="18090:5:1024 19091:400:1024"
# --- 2. relay close to Eventing, Splunk far (400 ms): Eventing sees only the relay's fast ack
run R400w8  PROFILE=200:60 RELAY=1 RELAY_TO=19092 SHIPPERS="ship_logs|$F|8|$HEC_RELAY|" MOCKS="19092:400:1024" METRICS=1
run R400w4  PROFILE=200:60 RELAY=1 RELAY_TO=19092 SHIPPERS="ship_logs|$F|4|$HEC_RELAY|" MOCKS="19092:400:1024" METRICS=1
# --- 3. Splunk latency sweep, direct, 200 orders/s: workers needed ~ rate x round trip
run L100w16 PROFILE=200:60 SHIPPERS="ship_logs|$F|16|$HEC_M1|" MOCKS="18090:100:1024" METRICS=1
run L100w32 PROFILE=200:60 SHIPPERS="ship_logs|$F|32|$HEC_M1|" MOCKS="18090:100:1024" METRICS=1
run L200w32 PROFILE=200:60 SHIPPERS="ship_logs|$F|32|$HEC_M1|" MOCKS="18090:200:1024" METRICS=1
run L200w64 PROFILE=200:60 SHIPPERS="ship_logs|$F|64|$HEC_M1|" MOCKS="18090:200:1024" METRICS=1
run L400w64 PROFILE=200:60 SHIPPERS="ship_logs|$F|64|$HEC_M1|" MOCKS="18090:400:1024" METRICS=1
# --- 4. scale-up, clean fast path, all levels
run S400w8  PROFILE=400:60 LOAD_WORKERS=16 LOAD_BATCH=40 SHIPPERS="ship_logs|$F|8|$HEC_M1|"  MOCKS="18090:5:1024" METRICS=1
run S400w16 PROFILE=400:60 LOAD_WORKERS=16 LOAD_BATCH=40 SHIPPERS="ship_logs|$F|16|$HEC_M1|" MOCKS="18090:5:1024" METRICS=1
run S800w16 PROFILE=800:60 LOAD_WORKERS=16 LOAD_BATCH=50 SHIPPERS="ship_logs|$F|16|$HEC_M1|" MOCKS="18090:5:1024" METRICS=1
run S800w32 PROFILE=800:60 LOAD_WORKERS=16 LOAD_BATCH=50 SHIPPERS="ship_logs|$F|32|$HEC_M1|" MOCKS="18090:5:1024" METRICS=1
# --- 5. sustained (10 min) and burst (100 -> 400 -> 100 orders/s)
run BU      PROFILE=100:60,400:60,100:60 LOAD_WORKERS=16 LOAD_BATCH=40 SHIPPERS="ship_logs|$F|16|$HEC_M1|" MOCKS="18090:5:1024" METRICS=1
run SU10    PROFILE=200:600 SHIPPERS="ship_logs|$F|8|$HEC_M1|" MOCKS="18090:5:1024" METRICS=1
echo "[$(date +%T)] ALL DONE" >> fv_matrix.log

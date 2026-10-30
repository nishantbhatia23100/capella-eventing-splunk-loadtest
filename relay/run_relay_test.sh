#!/bin/bash
# Local proof of the relay idea (no Docker, no Capella, no internet).
# "Splunk" = mock_hec.py with a 50 ms service time and a small connection limit.
set -u
cd "$(dirname "$0")"
LAT=${LAT:-50}; LIMIT=${LIMIT:-8}; DUR=${DUR:-8}
cleanup() { pkill -f "mock_hec.py --port 18088" 2>/dev/null; pkill -f "mini_relay.py --port 18089" 2>/dev/null; }
trap cleanup EXIT; cleanup; sleep 0.5

python3 ../mock_hec.py --port 18088 --latency-ms $LAT --max-conns $LIMIT --report-sec 1000 > /dev/null 2>&1 &
python3 mini_relay.py --port 18089 --downstream http://127.0.0.1:18088/services/collector/event --batch 500 --timeout 1 --flushers 2 > /dev/null 2>&1 &
sleep 1.5
SPL=http://127.0.0.1:18088/services/collector/event
REL=http://127.0.0.1:18089/services/collector/event

echo "== 'Splunk' = ${LAT} ms per call, ${LIMIT} concurrent connections max =="
python3 hec_load.py --target $SPL --workers 1  --duration $DUR --label "direct,  1 worker "
python3 hec_load.py --target $REL --workers 1  --duration $DUR --label "relay,   1 worker "
python3 hec_load.py --target $SPL --workers 16 --duration $DUR --label "direct, 16 workers"
python3 hec_load.py --target $REL --workers 16 --duration $DUR --label "relay,  16 workers"
sleep 2.5
echo; echo "relay stats :"; curl -s http://127.0.0.1:18089/
echo; echo "'Splunk' saw:"; curl -s http://127.0.0.1:18088/stats; echo

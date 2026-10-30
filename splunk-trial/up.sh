#!/usr/bin/env bash
# Start the fresh Splunk trial and verify it: container healthy, license = trial, HEC accepting events.
#   ./up.sh            start + verify
#   ./up.sh down       stop (keeps data)       ./up.sh reset   stop and DELETE its data (volumes of this stack only)
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="${ENV_FILE:-$HOME/.loadtest-env}"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE: run ../setup_credentials.sh first"; exit 1; }
set -a; . "$ENV_FILE"; set +a
case "${1:-up}" in
  down)  docker compose down; exit 0;;
  reset) read -r -p "Delete the splunk-trial volumes (all indexed test data)? [y/N] " x; [ "$x" = y ] && docker compose down -v; exit 0;;
esac
MGMT="${SPLUNK_MGMT:-https://localhost:8089}"
docker compose up -d
echo "waiting for Splunk to become healthy (first start under amd64 emulation takes 3-6 minutes)..."
until [ "$(docker inspect -f '{{.State.Health.Status}}' splunk-trial 2>/dev/null)" = healthy ]; do
  printf '.'; sleep 10
done; echo
AUTH="admin:${SPLUNK_PASSWORD}"
echo "--- license"
curl -sk -u "$AUTH" "$MGMT/services/licenser/licenses?output_mode=json" |
  python3 -c 'import sys,json; [print(" ", e["name"][:12], e["content"].get("type"), "expires:", e["content"].get("expiration_time"), "status:", e["content"].get("status")) for e in json.load(sys.stdin)["entry"]]'
echo "--- disk guard (Docker VM disk is small; lower Splunk's free-space guard so indexing is not paused)"
curl -sk -u "$AUTH" "$MGMT/servicesNS/nobody/system/configs/conf-server/diskUsage" -d minFreeSpace=500 -o /dev/null -w "set minFreeSpace=500: HTTP %{http_code}\n"
curl -sk -u "$AUTH" "$MGMT/services/properties/server/diskUsage/minFreeSpace" ; echo
echo "--- index + HEC token (newer images ignore SPLUNK_HEC_TOKEN, so create them over REST; idempotent)"
curl -sk -u "$AUTH" "$MGMT/services/data/indexes" -d name=couchbase -d datatype=event -o /dev/null -w "index couchbase: HTTP %{http_code} (409 = exists)\n"
curl -sk -u "$AUTH" "$MGMT/servicesNS/nobody/splunk_httpinput/data/inputs/http/http" -d disabled=0 -d enableSSL=1 -d port=8088 -o /dev/null -w "global HEC: HTTP %{http_code}\n"
curl -sk -u "$AUTH" "$MGMT/servicesNS/nobody/splunk_httpinput/data/inputs/http" -d name=eventing-loadtest -d token="$HEC_TOKEN" -d index=couchbase -d indexes=couchbase -d sourcetype=couchbase:eventing -o /dev/null -w "HEC token: HTTP %{http_code} (409 = exists)\n"
sleep 5
echo "--- HEC test event (HEC speaks HTTPS or HTTP depending on image; trying both)"
for s in https http; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' -H "Authorization: Splunk ${HEC_TOKEN}" \
    -d '{"event":"splunk-trial smoke test","sourcetype":"smoke"}' "$s://localhost:${SPLUNK_HEC_PORT:-8088}/services/collector/event") && [ "$code" = 200 ] && { echo "HEC OK over $s"; break; } || echo "$s -> $code"
done
echo "--- search works? (the expired demo license blocked this)"
curl -sk -u "$AUTH" "$MGMT/services/search/jobs/export" -d search='| makeresults | eval ok="search works"' -d output_mode=json | head -c 300; echo
echo "UI: http://localhost:${SPLUNK_WEB_PORT:-8000}   user: admin"

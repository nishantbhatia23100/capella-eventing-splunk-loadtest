#!/usr/bin/env bash
# Interactive: prompts for the Capella API key, database password and a NEW Splunk admin password,
# and writes them to ~/.eventing-test-env (chmod 600). Secrets are typed hidden and never echoed or logged.
#   ./setup_credentials.sh        press Enter at any prompt to keep the value already in the file
set -euo pipefail
F="${ENV_FILE:-$HOME/.loadtest-env}"
if [ -f "$F" ]; then set +u; . "$F"; set -u; fi
: "${CB_USER:=}" "${CB_CONNSTR:=}" "${CAPELLA_API_KEY:=}" "${CB_PASS:=}" "${SPLUNK_PASSWORD:=}" "${HEC_TOKEN:=}"

ask()  { local v; read -r -p "$1 [${2:-}]: " v; printf '%s' "${v:-$2}"; }
asks() { local v; read -r -s -p "$1 ${2:+(Enter keeps the saved one)}: " v; echo >&2; printf '%s' "${v:-$2}"; }

CB_CONNSTR=$(ask "Cluster connection string" "$CB_CONNSTR")
CB_USER=$(ask "Database user" "$CB_USER")
CB_PASS=$(asks "Database password" "$CB_PASS")
CAPELLA_API_KEY=$(asks "Capella API key SECRET (the long secret, not the key id)" "$CAPELLA_API_KEY")
while :; do
  SPLUNK_PASSWORD=$(asks "NEW Splunk admin password (min 8 chars, you choose it)" "$SPLUNK_PASSWORD")
  [ "${#SPLUNK_PASSWORD}" -ge 8 ] && break; echo "too short"
done
[ -n "$HEC_TOKEN" ] || HEC_TOKEN=$(python3 -c 'import uuid; print(uuid.uuid4())')

umask 077
{
  echo "# written by setup_credentials.sh on $(date -u +%FT%TZ); delete when testing is done"
  for k in CAPELLA_API_KEY CB_PASS CB_USER CB_CONNSTR SPLUNK_PASSWORD HEC_TOKEN; do printf 'export %s=%q\n' "$k" "${!k}"; done
  printf 'export SPLUNK_AUTH=%q\n' "admin:${SPLUNK_PASSWORD}"
  echo 'export SPLUNK_MGMT=https://localhost:8089'
  # ORG_ID / PROJECT_ID / CLUSTER_ID live in ids.env
} > "$F"
chmod 600 "$F"
echo "saved $F (mode 600). Checking the Capella key..."
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${CAPELLA_API_KEY}" https://cloudapi.cloud.couchbase.com/v4/organizations)
case "$code" in
  200) echo "Capella API key OK";;
  401|403) echo "Capella rejected the key (HTTP $code): wrong secret, expired, or your current IP ($(curl -s https://api.ipify.org)) is not on the key's allowed list";;
  *) echo "unexpected HTTP $code";;
esac

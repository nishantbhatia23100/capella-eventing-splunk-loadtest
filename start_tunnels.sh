#!/bin/bash
# Quick Cloudflare tunnels for the full-volume tests: two mock endpoints and the relay.
#   18090 -> HEC_M1   19091 -> HEC_M2   8090 (relay) -> HEC_RELAY        written to tunnels/urls_fv.env
cd "$(dirname "$0")"; mkdir -p tunnels; : > tunnels/urls_fv.env
pkill -f "cloudflared tunnel" 2>/dev/null; sleep 1
i=0
for spec in "M1 18090" "M2 19091" "RELAY 8090"; do
  set -- $spec; log=tunnels/fv_$1.log
  nohup cloudflared tunnel --no-autoupdate --url http://localhost:$2 > $log 2>&1 &
  for _ in $(seq 40); do u=$(grep -o 'https://[a-z0-9-]*\.trycloudflare.com' $log | head -1); [ -n "$u" ] && break; sleep 2; done
  echo "export HEC_$1=$u/services/collector/event" >> tunnels/urls_fv.env
done
cat tunnels/urls_fv.env | sed -E 's#https://([a-z0-9-]{6})[a-z0-9-]*#https://\1…#'

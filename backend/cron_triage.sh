#!/bin/bash
# Auto-triage backlog issues via the FSL App API
# Called by cron every 4 hours during business hours

APP_URL="${FSLAPP_URL:-https://fslapp-nyaaa.azurewebsites.net}"
PIN="${ADMIN_PIN:-121838}"

response=$(curl -s -w "\n%{http_code}" -X POST \
  "${APP_URL}/api/issues/triage" \
  -H "X-Admin-Pin: ${PIN}" \
  -H "Content-Type: application/json")

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | head -1)

if [ "$http_code" = "200" ]; then
  count=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null)
  if [ "$count" != "0" ]; then
    echo "$(date '+%Y-%m-%d %H:%M') — Triaged $count issue(s)"
  fi
else
  echo "$(date '+%Y-%m-%d %H:%M') — Triage failed (HTTP $http_code): $body" >&2
fi

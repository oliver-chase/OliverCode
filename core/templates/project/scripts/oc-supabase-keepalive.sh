#!/bin/bash
# oc-supabase-keepalive -- Non-deployed Supabase keepalive
#
# For repos without Cloudflare deployment.
# Writes a row to _keepalive_log to prevent compute pause.
#
# Standalone script — runs under any cron runner (crontab, external scheduler);
# no agent or runtime dependency.
#
# Required env vars:
#   SUPABASE_URL
#   SUPABASE_SERVICE_ROLE_KEY
# Optional:
#   KEEPALIVE_SOURCE (default: "cron")
#
# Usage (crontab example, every 6 hours):
#   0 */6 * * * SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
#     /path/to/oc-supabase-keepalive.sh >> /path/to/keepalive.log 2>&1

set -euo pipefail

URL="${SUPABASE_URL:-}"
KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"
SOURCE="${KEEPALIVE_SOURCE:-cron}"

if [ -z "$URL" ] || [ -z "$KEY" ]; then
  echo "supabase-keepalive: SKIPPED - SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"
  exit 0
fi

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST \
  -H "apikey: $KEY" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=minimal" \
  -d "{\"source\":\"$SOURCE\"}" \
  "${URL}/rest/v1/_keepalive_log")

if [ "$STATUS" = "201" ]; then
  echo "supabase-keepalive: OK ($TIMESTAMP) source=$SOURCE"
else
  echo "supabase-keepalive: FAILED HTTP $STATUS ($TIMESTAMP)"
fi

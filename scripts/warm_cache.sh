#!/usr/bin/env bash
set -euo pipefail

# Usage:
# SERVICE_URL="https://bh-stats-page.onrender.com" ./scripts/warm_cache.sh


SERVICE_URL="${SERVICE_URL:-https://bh-stats-page.onrender.com}"

echo "Warming cache on $SERVICE_URL"

# If SERVICE_AUTH is set (e.g. "Bearer <token>"), include it in requests
AUTH_HEADER_OPTION=()
if [ -n "${SERVICE_AUTH:-}" ]; then
  AUTH_HEADER_OPTION=( -H "Authorization: ${SERVICE_AUTH}" )
fi

warm() {
  local url="$1"
  echo "  -> $url"
  curl -fsS "${AUTH_HEADER_OPTION[@]}" "$url" -o /dev/null || true
}

# Core dashboard endpoints to warm
warm "$SERVICE_URL/metrics/summary"
warm "$SERVICE_URL/api/insights/qa"
warm "$SERVICE_URL/metrics/today"
warm "$SERVICE_URL/metrics/monthly-momentum"
warm "$SERVICE_URL/metrics/engineers/leaderboard?scope=today&limit=10"

echo "Cache warm complete."

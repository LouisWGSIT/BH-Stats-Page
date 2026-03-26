#!/usr/bin/env bash
set -euo pipefail

# Usage:
# SERVICE_URL="https://bh-stats-page.onrender.com" SERVICE_AUTH="Bearer <token>" ./scripts/measure_endpoints.sh

SERVICE_URL="${SERVICE_URL:-https://bh-stats-page.onrender.com}"
AUTH_HEADER_OPTION=()
if [ -n "${SERVICE_AUTH:-}" ]; then
  AUTH_HEADER_OPTION=( -H "Authorization: ${SERVICE_AUTH}" )
fi

endpoints=(
  "/metrics/summary"
  "/api/insights/qa"
  "/metrics/today"
  "/metrics/monthly-momentum"
  "/metrics/engineers/leaderboard?scope=today&limit=10"
  "/metrics/all-time-totals"
  "/analytics/daily-totals"
)

echo "Measuring endpoints on ${SERVICE_URL}"
for ep in "${endpoints[@]}"; do
  url="${SERVICE_URL}${ep}"
  printf "\n-> %s\n" "$url"
  # time and status
  curl -s ${AUTH_HEADER_OPTION[@]} -w "HTTP/%{http_version} %{http_code} %{time_total}s\n" -o /dev/null "$url" || true
  # show first 200 bytes of body for a quick sanity check
  curl -s ${AUTH_HEADER_OPTION[@]} "$url" | head -c 200 || true
done

echo "\nMeasurement complete."

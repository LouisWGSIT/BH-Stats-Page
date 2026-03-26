#!/usr/bin/env bash
set -euo pipefail

HOST=${1:-http://localhost:8001}
echo "Waiting for ${HOST} to respond..."
for i in $(seq 1 60); do
  if curl -fsS "${HOST}/" >/dev/null 2>&1; then
    echo "${HOST} is up"
    break
  fi
  sleep 1
done

echo "Checking key endpoints..."
curl -fsS -I "${HOST}/" || true
curl -fsS -I "${HOST}/metrics/today" || true
curl -fsS -I "${HOST}/auth/status" || true
echo "Smoke checks completed."
#!/usr/bin/env bash
# Simple smoke test script that waits for the app then runs a few curl checks
set -euo pipefail
BASE_URL=${1:-http://localhost:8001}

echo "Waiting for ${BASE_URL} to become available..."
for i in {1..30}; do
  if curl -sS ${BASE_URL} >/dev/null 2>&1; then
    echo "${BASE_URL} is up"
    break
  fi
  sleep 1
done

echo "Checking endpoints:"
curl -sS -i ${BASE_URL}/ | sed -n '1,5p'
curl -sS -i ${BASE_URL}/metrics/records | sed -n '1,5p'
curl -sS -i ${BASE_URL}/analytics/daily-totals | sed -n '1,5p'

echo "Smoke tests complete."

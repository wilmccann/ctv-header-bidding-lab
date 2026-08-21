#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose up -d

echo "Waiting for Prebid Server to become healthy on http://localhost:8000 ..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/status >/dev/null 2>&1; then
    echo "Prebid Server is up: http://localhost:8000"
    exit 0
  fi
  sleep 1
done

echo "Prebid Server did not become ready in time. Check logs with:"
echo "  docker compose logs -f"
exit 1

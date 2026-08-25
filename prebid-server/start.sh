#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Building prebid-server image (first build compiles PBS from source with"
echo "the ortbvast hooks vendored in — this can take several minutes and"
echo "needs network access; later runs are cached)..."
docker compose build

docker compose up -d

echo "Waiting for Prebid Server to become healthy on http://localhost:8000 ..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8000/status >/dev/null 2>&1; then
    echo "Prebid Server is up: http://localhost:8000"
    echo "Prebid Cache is up:  http://localhost:2424"
    exit 0
  fi
  sleep 2
done

echo "Prebid Server did not become ready in time. Check logs with:"
echo "  docker compose logs -f"
exit 1

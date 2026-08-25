#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Building prebid-server DEBUG image (adds Delve, disables Go compiler"
echo "optimizations/inlining so breakpoints in modules/ortbvast are"
echo "reliable) — first build is a few minutes, later ones are cached..."
docker compose -f docker-compose.yml -f docker-compose.debug.yml build

docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d

echo "Waiting for Prebid Server to become healthy on http://localhost:8000 ..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8000/status >/dev/null 2>&1; then
    echo "Prebid Server is up: http://localhost:8000"
    echo "Prebid Cache is up:  http://localhost:2424"
    echo "Delve is listening:  localhost:2345 — attach from VS Code with the"
    echo "  \"Attach to Bouncer/Enricher (Docker)\" launch config."
    exit 0
  fi
  sleep 2
done

echo "Prebid Server did not become ready in time. Check logs with:"
echo "  docker compose -f docker-compose.yml -f docker-compose.debug.yml logs -f"
exit 1

#!/usr/bin/env bash
# Posts an oRTB request to the local Prebid Server harness, pulls the VAST
# `adm` out of each returned bid, and validates each one against the VAST
# 4.2 XSD in docs/. Requires the harness to be running (prebid-server/start.sh)
# and `xmllint` (libxml2) on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."

PBS_URL="${PBS_URL:-http://localhost:8000/openrtb2/auction}"
REQUEST_FILE="${1:-examples/flextechads-ortb-request-pbs-test.json}"
SCHEMA="docs/vast_4.2.xsd"

if [ ! -f "$SCHEMA" ]; then
  echo "Schema not found: $SCHEMA" >&2
  exit 1
fi

if ! command -v xmllint >/dev/null 2>&1; then
  echo "xmllint not found on PATH (install libxml2)" >&2
  exit 1
fi

if ! curl -sf http://localhost:8000/status >/dev/null 2>&1; then
  echo "Prebid Server isn't responding on :8000. Start it with prebid-server/start.sh" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "Requesting $REQUEST_FILE ..."
curl -sf -X POST "$PBS_URL" \
  -H "Content-Type: application/json" \
  --data-binary @"$REQUEST_FILE" \
  -o "$WORKDIR/response.json"

python3 - "$WORKDIR/response.json" "$WORKDIR" <<'PY'
import json
import pathlib
import sys

response_path, workdir = sys.argv[1], pathlib.Path(sys.argv[2])
with open(response_path) as f:
    response = json.load(f)

count = 0
for seatbid in response.get("seatbid", []):
    for bid in seatbid.get("bid", []):
        adm = bid.get("adm")
        if not adm:
            continue
        count += 1
        impid = bid.get("impid", "unknown")
        (workdir / f"vast-imp{impid}.xml").write_text(adm)

if count == 0:
    print("No bids with an adm found in the response:", file=sys.stderr)
    print(json.dumps(response, indent=2), file=sys.stderr)
    sys.exit(1)

print(f"Extracted {count} VAST document(s).")
PY

fail=0
for f in "$WORKDIR"/vast-imp*.xml; do
  [ -e "$f" ] || continue
  echo "--- $(basename "$f") ---"
  if xmllint --noout --schema "$SCHEMA" "$f"; then
    echo "OK: $(basename "$f") is valid VAST"
  else
    echo "FAIL: $(basename "$f") does not validate" >&2
    fail=1
  fi
done

exit "$fail"

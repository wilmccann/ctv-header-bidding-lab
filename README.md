# ortb-vast

Hand-crafted OpenRTB video bid request/response examples for CTV (connected TV)
header bidding, plus a local Prebid Server test harness for validating them
against a real auction/response pipeline. It models a small multi-publisher
exchange: two mock 3rd-party STV publishers, three competing DSPs (including
a 1st-party "house-dsp" seat), Prebid Cache, and a pre-auction filter/
enrichment stage, all running as a custom-built Prebid Server image.

**Start with [`ARCHITECTURE.md`](docs/ARCHITECTURE.md)** if you're new to this
repo — it explains how Prebid Server's exchange actually matches an STV bid
request to demand partners, and walks through why each piece below exists.

## What's here

### `examples/`

- **`flextechads-ortb-request.json`** — a spec-shaped OpenRTB 2.5/2.6 `BidRequest`
  for a mock exchange ("FlexTechAds"). Represents a Roku CTV app requesting a
  3-slot in-stream video ad pod (linear, 6-35s, 1080p, VAST 4.0/4.3), each
  impression contestable by both a private marketplace (PMP) deal and the open
  auction floor. Uses GPP (`regs.gpp` / `regs.gpp_sid`) for privacy signaling.
- **`flextechads-ortb-request-pbs-test.json`** — the same request, with each
  impression tagged under `ext.prebid.storedauctionresponse` so it can be
  pointed at Prebid Server's stored-response fixtures instead of a live bidder.
- **`flextechads-ortb-request-pbs-test-multidsp.json`** — imp 1 repointed at
  a 3-seat stored response (`house-dsp`, `nova-dsp`, `orbit-dsp`) so the
  auction actually has competing demand to rank, instead of one canned bid.
- **`circuittv-ortb-request-pbs-test.json`** — a **second** STV publisher
  ("CircuitTV", a Samsung Tizen app) with its own PBS account, its own
  floors and deal in the request, and the same 3-DSP demand pool bidding
  across both publishers.
- **`flextechads-ortb-request-pbs-test-{debug,floor,targeting}.json`** —
  single-change variants of the PBS test request (debug trace, raised imp
  floor, targeting keys), each described in [`TESTING.md`](docs/TESTING.md).

### `docs/`

- **[`ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — how PBS matches STV
  requests to demand, and how this repo's pieces fit together.
- **[`TESTING.md`](docs/TESTING.md)** — curl recipes and what each pytest
  module covers.
- **[`RETROSPECTIVE-delve-debugging.md`](docs/RETROSPECTIVE-delve-debugging.md)**
  — why Delve breakpoints silently failed under Rosetta emulation, and the fix.
- **`vast_4.2.xsd`** — the IAB VAST 4.2 schema, used by
  `scripts/validate-vast.sh` (see [Third-party material](#third-party-material)).

[`prebid-server/README-build.md`](prebid-server/README-build.md) covers
building, debugging (Delve + VS Code), and upgrading the custom PBS image.

### `modules/ortbvast/`

Custom Prebid Server Go modules — PBS's real Hooks/Modules extension point,
compiled into the binary (there's no runtime plugin loading). See
`ARCHITECTURE.md` §4 for the design.

- **`bouncer/`** — `entrypoint`-stage hook: an in-process Bloom filter
  checking the request's source IP against a known-bad list, rejecting
  matches before the body is even parsed.
- **`enricher/`** — `raw_auction_request`-stage hook: looks up `device.ifa`
  against a mock in-memory profile store (standing in for Aerospike/Redis/
  ScyllaDB) and decorates the request with `user.data[]` audience segments
  before any DSP — mock or real — sees it.

### `prebid-server/`

A **custom-built** [Prebid Server](https://docs.prebid.org/prebid-server/overview/prebid-server-overview.html)
(Go) instance — built from source via `Dockerfile` (not the stock
`prebid/prebid-server` image) so the `ortbvast` hooks above are compiled in —
plus a `prebid-cache` sidecar container, configured to serve **stored
auction responses**: a real, documented PBS testing feature that lets canned
bid responses flow through the actual auction/response pipeline (request
validation, GPP-aware privacy parsing, deal-vs-open-floor logic, targeting/
VAST assembly, caching) without calling any real bidder adapter.

```
prebid-server/
  Dockerfile            # clones + builds PBS from source with modules/ortbvast/ vendored in
  Dockerfile.debug      # same build, unoptimized and launched under Delve
  docker-compose.yml    # builds prebid-server, runs prebid/prebid-cache:v0.30.0
  docker-compose.debug.yml  # overlay: swaps in Dockerfile.debug, exposes Delve on :2345
  pbs.yaml              # accounts, cache, hooks (bouncer/enricher) config
  start.sh / stop.sh    # build + bring the stack up/down
  start-debug.sh        # build + bring up the Delve-enabled stack
  README-build.md       # build, verify, debug, upgrade
  cache-config/
    bouncer-blocklist.txt      # IPs the Bouncer rejects
    enricher-profiles.json     # mock device-ID → audience-segment store
  stored_requests/data/by_id/
    accounts/
      flex-pub-001.json        # FlexTechAds account (default targeting prefix)
      circuit-pub-001.json     # CircuitTV account (custom "ctv_" prefix, its own cache TTL)
    stored_responses/
      flex-resp-imp1..3.json           # original single-seat fixtures
      flex-resp-imp1-multidsp.json     # 3-seat competing-DSP fixture
      flex-resp-imp3-nobid.json        # seat with an empty bid[] (partial no-bid test)
      circuit-resp-imp1..2.json        # CircuitTV's 3-seat fixtures
```

### `tests/`

A pytest integration suite exercising all of the above against the live
harness — see [`TESTING.md`](docs/TESTING.md) for what each test covers.

### `scripts/`

- **`validate-vast.sh [request.json]`** — posts a request to the running
  harness and validates each bid's VAST against `docs/vast_4.2.xsd`. Needs
  `xmllint` (libxml2; preinstalled on macOS). On the default request it
  exits non-zero **by design**: `flex-resp-imp3.json` is an intentionally
  invalid fixture (see `TESTING.md`).

## Running the Prebid Server harness

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(amd64 or Apple Silicon) and, for the test suite, Python 3.9+.

```bash
cd prebid-server
./start.sh    # docker compose build (first run compiles PBS from source —
              # several minutes), then docker compose up -d, waits for
              # /status to go healthy
cd ..
```

Then, from the repo root, send a test request:

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-multidsp.json | python3 -m json.tool
```

You should get back a `BidResponse` with bids from all three DSP seats on
imp 1 (`house-dsp` $11 open, `nova-dsp` $10 with the PMP deal, `orbit-dsp`
$9.25 open), plus the original single-seat imps 2/3, each with a VAST `adm`.

Run the full integration suite instead of hand-checking curl output:

```bash
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/pytest tests/
```

Stop the stack with:

```bash
prebid-server/stop.sh     # docker compose down
```

**Note:** stored-response and account fixtures are loaded into memory once
at server startup. If you edit anything under `stored_requests/` or
`cache-config/`, or `pbs.yaml`, restart the stack
(`prebid-server/stop.sh && prebid-server/start.sh`) to pick up the change.
Editing `modules/ortbvast/*` requires a rebuild (`docker compose build`),
since those are compiled into the binary.

To step through the Bouncer/Enricher Go code with a debugger, use
`prebid-server/start-debug.sh` and the VS Code attach configuration in
`.vscode/launch.json` — walkthrough in
[`prebid-server/README-build.md`](prebid-server/README-build.md#debugging-the-compiled-hooks-bouncerenricher-in-vs-code).

## License

[MIT](LICENSE), except as noted below.

### Third-party material

- **`docs/vast_4.2.xsd`** is the IAB Tech Lab VAST 4.2 schema, included
  unmodified from [InteractiveAdvertisingBureau/vast](https://github.com/InteractiveAdvertisingBureau/vast)
  so `scripts/validate-vast.sh` works offline. It remains IAB Tech Lab's
  material, is not covered by this repo's MIT license, and is subject to
  that repository's terms.
- Prebid Server and Prebid Cache are cloned/pulled at build time and are
  licensed by Prebid.org under Apache 2.0; neither is redistributed here.

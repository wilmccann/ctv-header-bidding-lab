# Testing

## Running the suite

The fastest path is the pytest integration suite in `tests/`, which covers
everything below programmatically:

```bash
cd prebid-server && ./start.sh   # first run builds the custom PBS image
cd ..
pip install -r tests/requirements.txt
pytest tests/
```

The manual curl recipes below remain useful for exploring a response by
hand or debugging a failing test; each pytest module's docstring says which
recipe it replaces/extends.

## Test Cases

Runnable request variants against the local Prebid Server harness. Each is a
full copy of a baseline fixture with exactly one thing changed, so the diff
against the baseline is the thing being tested. Requires the harness running
(`cd prebid-server && ./start.sh`).

### Debug-mode trace

`examples/flextechads-ortb-request-pbs-test-debug.json` · pytest:
`tests/test_debug_trace.py`

**Run:**

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-debug.json | python3 -m json.tool
```

**Tests:** the standard 3-imp auction, with `test: 1` and
`ext.prebid.debug: true` set so PBS returns its internal debug trace
alongside the bids instead of just the final `BidResponse`.

**Look for:** `ext.debug.resolvedrequest` — it's the *last* key in the
response, after all 3 bids' `adm` blobs, so scroll/grep past them. It's the
fully-merged request PBS actually ran (stored-request/response resolution,
generated `source.tid`, echoed `ext.prebid.debug: true`, and — now that the
Enricher module is wired up — a `user.data[]` block from
`ortbvast-mock-idsp` if `device.ifa` matched an entry in
`prebid-server/cache-config/enricher-profiles.json`). To skip straight to
it:

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-debug.json \
  | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['ext']['debug'], indent=2))"
```

### Floor-vs-deal edge case

`examples/flextechads-ortb-request-pbs-test-floor.json` · pytest:
`tests/test_deal_and_floor.py`

**Run:**

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-floor.json \
  | python3 -c "
import json, sys
for sb in json.load(sys.stdin)['seatbid']:
    for b in sb['bid']:
        print(b['impid'], b['price'], b.get('dealid'))
"
```

**Tests:** whether PBS enforces the imp-level `bidfloor` against a bid
sourced from `ext.prebid.storedauctionresponse`. `imp[0].bidfloor` is raised
to `20` — above both the deal's own `pmp.deals[0].bidfloor: 10` and the
stored bid's actual price of `10.0` — while the deal object itself is left
untouched.

**Look for:** the printed line for `impid "1"` — it should still read
`1 10 FLEXTECHADS-PMP-DEAL-001`. The bid comes through despite being priced
below the general imp floor, confirming floor enforcement isn't applied to
stored auction response bids.

### Multi-DSP exchange matching

`examples/flextechads-ortb-request-pbs-test-multidsp.json` · pytest:
`tests/test_multi_dsp_auction.py`

**Run:**

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-multidsp.json \
  | python3 -c "
import json, sys
for sb in json.load(sys.stdin)['seatbid']:
    for b in sb['bid']:
        print(sb['seat'], b['impid'], b['price'], b.get('dealid'))
"
```

**Tests:** imp 1's stored response now carries 3 competing seats
(`house-dsp` $11 open, `nova-dsp` $10 with `FLEXTECHADS-PMP-DEAL-001`,
`orbit-dsp` $9.25 open) instead of one. This is the actual "matching STV
requests with DSP demand" mechanism described in `ARCHITECTURE.md` §2: PBS
keeps every valid bid in `seatbid[]` and separately computes which one gets
the unprefixed `hb_*` targeting keys.

**Look for:** all 3 seats present with their respective prices/dealid; in
the targeting output (request already sets `ext.prebid.targeting: {}`),
`house-dsp`'s bid on imp 1 carries the generic `hb_bidder`/`hb_pb` keys
(it has the highest price), every seat has its own `hb_pb_<seat>` key, and
only `nova-dsp`'s bid carries `hb_deal`.

### Publisher account isolation

`examples/circuittv-ortb-request-pbs-test.json` · pytest:
`tests/test_publisher_isolation.py`

**Run:**

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/circuittv-ortb-request-pbs-test.json \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
for sb in data['seatbid']:
    for b in sb['bid']:
        print(sb['seat'], b['impid'], b['price'], sorted(b.get('ext', {}).get('prebid', {}).get('targeting', {})))
"
```

**Tests:** a second publisher (`circuit-pub-001`, CircuitTV/OrbitWatch on a
Samsung Tizen device) resolving to its own account config
(`prebid-server/stored_requests/data/by_id/accounts/circuit-pub-001.json`),
which sets `targeting_prefix: "ctv_"` instead of the default `hb_`.

**Look for:** every targeting key on CircuitTV's bids starts with `ctv_`
(e.g. `ctv_pb`, `ctv_bidder`), never `hb_` — proof the two publishers'
config is actually isolated, not just cosmetically separate fixtures.
Posting the same request with an unregistered `app.publisher.id` should
fail outright (`account_required: true`), rather than silently falling
back to defaults.

### Pre-bid Bouncer / Enricher pipeline

`modules/ortbvast/{bouncer,enricher}/` · pytest:
`tests/test_bouncer_and_enricher.py`

**Run (Bouncer):**

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-For: 192.0.2.66" \
  --data-binary @examples/flextechads-ortb-request-pbs-test.json -w '\n%{http_code}\n'
```

**Tests:** `192.0.2.66` is in `prebid-server/cache-config/bouncer-blocklist.txt`.
The Bouncer module runs at the `entrypoint` stage, before the request body
is even parsed, and should reject this before the auction runs.

**Run (Enricher):** the debug-mode recipe above, then check
`ext.debug.resolvedrequest.user.data` for a `name: "ortbvast-mock-idsp"`
block — `device.ifa` in that fixture matches an entry in
`prebid-server/cache-config/enricher-profiles.json`.

**Caveat:** both modules require the custom-built image
(`prebid-server/Dockerfile`) and their exact runtime behavior — especially
the Bouncer's HTTP status code on rejection — was not verified against a
running instance while authoring this (see `ARCHITECTURE.md` §4, "A note on
confidence"). Run these first after any change to confirm the assumptions
in the module code hold, and adjust `tests/test_bouncer_and_enricher.py`'s
assertions to match what you actually see.

### VAST cache round-trip

`examples/flextechads-ortb-request-pbs-test-multidsp.json` (already sets
`ext.prebid.cache.vastxml: {}`) · pytest: `tests/test_cache_roundtrip.py`

**Run:**

```bash
CACHE_ID=$(curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-multidsp.json \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
for sb in data['seatbid']:
    for b in sb['bid']:
        t = b.get('ext', {}).get('prebid', {}).get('targeting', {})
        if 'hb_cache_id' in t:
            print(t['hb_cache_id']); break
")
curl -s "http://localhost:2424/cache?uuid=$CACHE_ID"
```

**Tests:** the `prebid-cache` service (added in `docker-compose.yml`) and
`pbs.yaml`'s `cache:` block actually work end to end — this was previously
a documented no-op in this repo (no cache service, no config).

**Look for:** a `hb_cache_id` targeting key in the auction response, and the
`GET /cache` call returning the same VAST XML that was in the winning bid's
`adm`.

## Test Ideas

- [x] **Debug-mode request** — see [Debug-mode trace](#debug-mode-trace).
- [x] **Targeting key-values** — see
      `examples/flextechads-ortb-request-pbs-test-targeting.json` (unchanged
      from the original harness; still demonstrates `hb_deal` present/absent
      per bid and the `hb_bidder_flextechad` 20-char GAM key-name truncation).
- [x] **Floor-vs-deal edge case** — see
      [Floor-vs-deal edge case](#floor-vs-deal-edge-case).
- [x] **VAST schema validation** — `scripts/validate-vast.sh`, unchanged
      from the original harness. `flex-resp-imp1.json`/`flex-resp-imp2.json`
      validate; `flex-resp-imp3.json` is left intentionally invalid as a
      known-failing case. The new multi-DSP and CircuitTV fixtures follow
      the same validated element ordering (`Impression` before
      `AdServingId`/`AdTitle`, `TrackingEvents` before `Duration`/
      `MediaFiles`, `UniversalAdId` present on every `Creative`) — worth
      re-running `scripts/validate-vast.sh` against them if you add more.
- [x] **Cache round-trip** — see
      [VAST cache round-trip](#vast-cache-round-trip). Was a documented
      no-op; now testable now that `prebid-cache` and `cache:` config exist.
- [x] **Partial no-bid case** — `tests/test_partial_no_bid.py`: removes
      `ext.prebid.storedauctionresponse` from one imp with no real bidder
      configured; confirms PBS returns the other 2 bids plus a clean no-bid
      for that slot instead of erroring the whole auction.
- [x] **Multi-DSP exchange matching** — see
      [Multi-DSP exchange matching](#multi-dsp-exchange-matching).
- [x] **Publisher account isolation** — see
      [Publisher account isolation](#publisher-account-isolation).
- [x] **Pre-bid Bouncer / Enricher pipeline** — see
      [Pre-bid Bouncer / Enricher pipeline](#pre-bid-bouncer--enricher-pipeline)
      — status: implemented, **not yet verified against a running build**
      (see the caveat in that section).
- [ ] **GPP opt-out variants** — swap `regs.gpp` for a USNAT string with the
      sale/share opt-out bits set, or set `regs.coppa: 1`, and check whether
      `device.ifa` / `device.geo` precision get stripped. Still open.
- [ ] **Concurrent requests** — fire ~20 parallel requests at
      `/openrtb2/auction` and confirm the static/deterministic responses stay
      consistent under load. Still open; would also be a reasonable check
      that the Bouncer's Bloom filter and the Enricher's mock KV store are
      safe for concurrent access (both are read-mostly after startup, so
      this should hold, but hasn't been load-tested).

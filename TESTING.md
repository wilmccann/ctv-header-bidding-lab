# Testing

## Test Cases

Runnable request variants against the local Prebid Server harness. Each is a
full copy of `examples/flextechads-ortb-request-pbs-test.json` with exactly
one thing changed, so the diff against the baseline fixture is the thing
being tested. Requires the harness running (`cd prebid-server && ./start.sh`).

### Debug-mode trace

`examples/flextechads-ortb-request-pbs-test-debug.json`

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
generated `source.tid`, echoed `ext.prebid.debug: true`). To skip straight
to it:

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-debug.json \
  | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['ext']['debug'], indent=2))"
```

### Floor-vs-deal edge case

`examples/flextechads-ortb-request-pbs-test-floor.json`

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

### Targeting key-values

`examples/flextechads-ortb-request-pbs-test-targeting.json`

**Run:**

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test-targeting.json \
  | python3 -c "
import json, sys
for sb in json.load(sys.stdin)['seatbid']:
    for b in sb['bid']:
        print(b['impid'], '->', b['ext']['prebid']['targeting'])
"
```

**Tests:** whether PBS generates ad-server targeting key-values (the `hb_*`
macros a GAM/DFP line item would read) for stored-response bids, given
`ext.prebid.targeting: {}` on the request.

**Look for:** each bid's targeting map containing `hb_pb`, `hb_bidder`,
`hb_size`, `hb_env` — both generic (`hb_pb`) and per-bidder
(`hb_pb_flextechads`) keys — plus `hb_deal` on the two deal bids (imp 1 and
2) but *not* on imp 3, the open-auction win. That `hb_deal` present/absent
split is the meaningful check here: it's PBS correctly distinguishing "this
bid came from a private deal" vs "this bid won the open floor" in the
targeting output, not just in the raw bid (`dealid` field). Everything else
(`hb_pb`, `hb_bidder`, `hb_size`, `hb_env`) is expected to be non-empty on
all 3 bids regardless of deal status — that just confirms targeting
generation runs at all for stored-response bids.

Two things in the output that look like bugs but aren't:
- The per-bidder keys use `_flextechads` as a suffix; with only one seat
  configured, they're always identical to the generic key.
- `hb_bidder_flextechad` is missing the trailing `s` — PBS truncates
  per-bidder key names to stay under GAM's historical 20-character key-name
  limit.

## Test Ideas

Beyond posting `examples/flextechads-ortb-request-pbs-test.json` and checking for
3 canned bids, these exercise the auction pipeline and spec conformance around
those fixtures rather than just the fixtures themselves.

- [x] **Debug-mode request** — see [Test Cases](#debug-mode-trace) above.
- [x] **Targeting key-values** — see [Test Cases](#targeting-key-values)
      above.
- [ ] **Cache round-trip** — add `ext.prebid.cache.vastxml: {}` and confirm
      a `hb_cache_id`/`hb_uuid` targeting key appears, then
      `GET /cache?uuid=<id>` and confirm the cached VAST matches the stored
      fixture. Confirmed this is currently a silent no-op: `pbs.yaml` has no
      `cache:` config and `docker-compose.yml` has no `prebid-cache`
      service, so PBS has nothing to call out to. Needs a second container
      (`prebid/prebid-cache`) plus `cache: {host, path}` config before this
      is testable — bigger lift than the other items here.
- [x] **Floor-vs-deal edge case** — see
      [Test Cases](#floor-vs-deal-edge-case) above.
- [ ] **GPP opt-out variants** — swap `regs.gpp` for a USNAT string with the
      sale/share opt-out bits set, or set `regs.coppa: 1`, and check whether
      `device.ifa` / `device.geo` precision get stripped.
- [ ] **Partial no-bid case** — remove `ext.prebid.storedauctionresponse` from
      one imp with no real bidder configured; confirm PBS returns the other
      2 bids plus a clean no-bid for that slot instead of erroring the whole
      auction.
- [x] **VAST schema validation** — pull each bid's `adm` out of a live auction
      response and validate it against `docs/vast_4.2.xsd`.
      → `scripts/validate-vast.sh`. `flex-resp-imp1.json` and
      `flex-resp-imp2.json` were fixed to pass; `flex-resp-imp3.json` is
      left intentionally invalid as a known-failing case. The XSD is
      stricter than it first looks: `xs:extension` means a derived type's
      elements are appended *after* its base type's, not interleaved by
      logical grouping — so `Impression` (from the base `AdDefinitionBase_type`)
      must precede `AdServingId`/`AdTitle` (from the derived `Inline_type`),
      and `TrackingEvents` (base `Linear_Base_type`) must precede
      `Duration`/`MediaFiles` (derived `Linear_Inline_type`). `Creative` also
      requires a `UniversalAdId` element (min 1) after `Linear`, which the
      original hand-crafted fixtures omitted entirely.
- [ ] **Concurrent requests** — fire ~20 parallel requests at
      `/openrtb2/auction` and confirm the static/deterministic responses stay
      consistent under load.

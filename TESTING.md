# Test ideas

Beyond posting `examples/flextechads-ortb-request-pbs-test.json` and checking for
3 canned bids, these exercise the auction pipeline and spec conformance around
those fixtures rather than just the fixtures themselves.

- [x] **Debug-mode request** — `test: 1` + `ext.prebid.debug: true` to see
      `ext.debug.resolvedrequest`, per-imp timing, and any floor/GPP warnings
      PBS attaches, instead of just the final bids.
      → `examples/flextechads-ortb-request-pbs-test-debug.json`
- [ ] **Targeting + cache round-trip** — add `ext.prebid.targeting` and
      `ext.prebid.cache.vastxml` to the request, then `GET /cache?uuid=<hb_cache_id>`
      and confirm the cached VAST matches the stored fixture.
- [x] **Floor-vs-deal edge case** — raise `imp[0].bidfloor` above the deal
      fixture's `10.0` price (leaving the deal's own `bidfloor: 10` alone) and
      see whether PBS filters the stored-response bid or lets it through
      unchecked. Result: unchecked — with `bidfloor` raised to `20`, PBS still
      returned the `$10` deal bid, so floor enforcement isn't applied to
      stored auction responses.
      → `examples/flextechads-ortb-request-pbs-test-floor.json`
- [ ] **GPP opt-out variants** — swap `regs.gpp` for a USNAT string with the
      sale/share opt-out bits set, or set `regs.coppa: 1`, and check whether
      `device.ifa` / `device.geo` precision get stripped.
- [ ] **Partial no-bid case** — remove `ext.prebid.storedauctionresponse` from
      one imp with no real bidder configured; confirm PBS returns the other
      2 bids plus a clean no-bid for that slot instead of erroring the whole
      auction.
- [x] **VAST schema validation** — pull each bid's `adm` out of a live auction
      response and validate it against `docs/vast_4.2.xsd`.
      → `scripts/validate-vast.sh`
- [ ] **Concurrent requests** — fire ~20 parallel requests at
      `/openrtb2/auction` and confirm the static/deterministic responses stay
      consistent under load.

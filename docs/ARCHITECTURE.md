# Architecture: `ortb-vast` as an STV/CTV Exchange

This document reviews where the repo stands today, explains how Prebid Server's
exchange actually matches a Streaming TV (STV/CTV) bid request to demand
partners, and lays out the changes needed to run this as a small multi-publisher
hub: third-party STV publishers send OpenRTB in, multiple DSPs (including a
first-party "house DSP" stand-in) compete for each impression, and a
pre-auction filter/enrichment stage sits in front of the auction itself.

---

## 1. Current state

What's here today is a **stored-response test harness**, not an exchange:

```
docker-compose.yml → prebid/prebid-server:v4.8.0 (stock image), single container
pbs.yaml           → account_required: false, gdpr default "0", no cache config
stored_requests/   → stored_responses only, one seat ("flextechads"), one publisher
examples/          → one CTV app (StreamVault/Roku), 3 imps, all wired to storedauctionresponse
```

Every bid in every fixture is canned JSON injected directly into the auction
pipeline via PBS's `ext.prebid.storedauctionresponse` feature. That's a real,
documented PBS capability — the request still goes through validation, GPP
parsing, deal-vs-floor logic, targeting-key generation, and VAST assembly —
but no bidder adapter is ever called, there's no concept of "publisher A vs.
publisher B," and nothing inspects the request before the auction runs. It's
good for asserting PBS's response-shaping behavior; it doesn't yet model a
hub that ingests real 3rd-party traffic.

Gaps against the target scenario:

| Gap | Why it matters |
|---|---|
| Single publisher, `account_required: false` | A multi-publisher exchange is multi-tenant — each STV publisher needs its own account (floors, allowed demand, privacy defaults) isolated from the others |
| Single mock seat | Doesn't demonstrate multiple DSPs (1st-party + 3rd-party) actually competing for the same impression |
| No Prebid Cache | STV/CTV responses are typically too large for inline VAST in the ad response; real setups return a cache URL (`hb_cache_id`) instead |
| No pre-auction filtering/enrichment | Nothing stands between "request hits PBS" and "auction runs" — no bot/fraud filtering, no identity decoration |
| Stock PBS image | Any pre-auction logic beyond config (floors, GDPR, stored responses) requires a **custom-built** PBS binary — modules are compiled in, not dynamically loaded |

---

## 2. How Prebid Server's exchange actually matches STV requests to demand

This is the mental model worth having before touching config. PBS is not a
matching *algorithm* in the ad-network sense (no ML ranking, no real-time
bidding strategy) — it's an **aggregator and rules engine**. The intelligence
of "who wins" is split between PBS (floor/deal enforcement, price-based
ranking for targeting) and the downstream ad server (GAM/DFP, which is the
thing that actually picks a single winning line item using the price
key-values PBS hands it). Concretely, one `/openrtb2/auction` call goes
through:

1. **Entrypoint** — raw HTTP request lands, before any JSON parsing. This is
   where header-only checks (IP reputation, obvious bot UAs) are cheapest,
   because you haven't paid the cost of unmarshaling the body yet.
2. **Stored request resolution** — PBS looks up the account (publisher) by
   `app.publisher.id` (or a query param, depending on setup), merges any
   stored default request/imp config for that account (default currency,
   allowed bidders, privacy defaults, price granularity) with what the
   publisher actually sent. This is the multi-tenancy point: two STV
   publishers hitting the same PBS instance get different defaults because
   they resolve to different accounts.
3. **Validation** — required OpenRTB fields, GPP (`regs.gpp`/`gpp_sid`),
   COPPA, video object completeness (`mimes`, `protocols`, `w`/`h` or
   `wmax`/`hmax`, `plcmt`) — CTV requests fail here more often than display,
   because the video object has more required fields.
4. **Per-imp bidder fan-out** — for each `imp`, PBS looks at
   `imp.ext.prebid.bidder.{bidderName}` and, for every bidder named there,
   builds a bidder-specific request (via that adapter's request builder) and
   calls it *in parallel*, bounded by `tmax`. This is the actual "matching"
   step in a live system: each configured DSP adapter gets a fan-out call for
   every impression it's eligible for. In this repo, `storedauctionresponse`
   *replaces* this step with canned data — no network call happens — which is
   exactly why it's suitable for a demand-side mock but not for exercising
   real adapter code.
5. **Bid collection & normalization** — currency conversion to the request's
   `cur`, dropping bids below `imp.bidfloor` (unless sourced from a stored
   response — PBS does not floor-enforce those, which is the "floor-vs-deal"
   behavior already documented in `TESTING.md`), dropping bids for
   categories in `bcat` or advertisers in `badv`.
6. **Auction / targeting** — PBS does *not* discard losing bids. It returns
   every valid bid from every seat in `seatbid`, but it also computes ad-server
   targeting key-values per imp: the highest-price bid per impression gets the
   unprefixed keys (`hb_pb`, `hb_bidder`, `hb_deal`) when
   `includewinners: true`, and every bid gets bidder-prefixed keys
   (`hb_pb_<bidder>`) when `includebidderkeys: true`. **This is the actual
   matching mechanism for STV**: when three DSPs (say `house-dsp`,
   `nova-dsp`, `orbit-dsp`) all bid on the same impression, PBS's job is to
   rank them and hand the ad server (or, in a server-side CTV setup, your own
   ad-decisioning layer) the price-ranked key-values to decide with — not to
   silently drop the losers.
7. **Deal precedence** — a bid carrying a `dealid` that matches one of the
   impression's `pmp.deals[]` is still ranked by price against open-auction
   bids by default (`at: 1`, first-price), but its presence is preserved in
   targeting (`hb_deal`) so a downstream system can prefer it regardless of
   price if that's the desired business rule (PMP deals are usually meant to
   guarantee access/priority, not just compete on price — enforcing that
   priority is a line-item/ad-server-side decision, not something PBS imposes
   for you out of the box).
8. **VAST/creative assembly & caching** — for video, `adm` is either the
   inline VAST XML (small pods) or, with `ext.prebid.cache.vastxml: {}` set
   and a `cache:` target configured, PBS POSTs the VAST to Prebid Cache and
   returns a `hb_cache_id` / `hb_uuid` targeting key plus a cache URL instead
   — this is what most real CTV integrations do, since player-side payload
   size and parse time matter more on set-top hardware.
9. **Response assembly** — final `BidResponse` with `seatbid[]`, targeting,
   and (if requested) `ext.debug.resolvedrequest` showing exactly what PBS
   ran after all the merges above — the single best way to observe what a
   pre-auction module actually changed, since it's the fully-resolved request
   PBS acted on.

For a multi-publisher exchange, "matching STV bid requests with demand" is really
steps 2 (which publisher/account, which allowed DSPs), 4 (fan-out to those
DSPs — real or mocked), and 6–7 (rank and expose via targeting, respecting
deal priority). Nothing about it is CTV-specific at the protocol level; what
makes it CTV/STV-specific is almost entirely in the `video` object shape and
in step 8 (cache-first delivery), because inline creative payload behaves
differently in a video player than in a banner.

---

## 3. Target architecture (multi-publisher exchange)

```
                     ┌─────────────────────────────────────────────────────┐
                     │                   Prebid Server                     │
 3rd-party STV       │  ┌───────────┐   ┌────────────┐   ┌───────────────┐ │        DSPs
 publishers          │  │ Entrypoint│   │RawAuction  │   │  Bidder fan-   │ │  ┌─────────────┐
 (PlutoTV-style,     │  │  hook:    │──▶│Request hook│──▶│  out (parallel,│─┼─▶│ house-dsp   │
  FlexTechAds,       ├─▶│  Bouncer  │   │: Enricher  │   │  bound by tmax)│ │  │ (1st party)  │
  CircuitTV, ...)    │  │(bloom     │   │(identity   │   │                │ │  ├─────────────┤
                     │  │ filter)   │   │ decoration)│   │  storedauction-│ │  │ nova-dsp     │
 POST                │  └───────────┘   └────────────┘   │  response for  │─┼─▶│ (3rd party)  │
 /openrtb2/auction   │        │                │         │  mock DSPs;    │ │  ├─────────────┤
                     │        │ reject (NBR)   │ user.data,│  real adapter  │─┼─▶│ orbit-dsp    │
                     │        ▼                │ ext decor │  for live ones│ │  │ (3rd party)  │
                     │   204 / no-bid           ▼           └───────────────┘ │  └─────────────┘
                     │              ┌─────────────────────┐                  │
                     │              │ Stored request /     │                 │
                     │              │ account resolution   │                 │
                     │              │ (per-publisher config)│                │
                     │              └─────────────────────┘                  │
                     │                        │                              │
                     │                        ▼                              │
                     │        Auction: floor/deal rules, targeting keys,     │
                     │        VAST assembly ──▶ Prebid Cache (hb_cache_id)   │
                     └─────────────────────────────────────────────────────┘
                                          │
                                          ▼
                              BidResponse → back to publisher
```

Key design points:

- **Accounts = publishers.** Each 3rd-party STV publisher gets its own PBS
  account (`stored_requests/data/by_id/accounts/<id>.json`), with
  `account_required: true` enforced so an unrecognized publisher ID is
  rejected outright rather than silently falling back to global defaults.
- **Seats = demand partners.** `house-dsp` is modeled as just another seat
  in the auction — architecturally there's no special-casing for "the house
  DSP" at the PBS layer; any priority the exchange's own demand should get (e.g.
  first look, floor discount) is a business rule expressed as a deal or a
  targeting-consumption rule downstream, exactly like any other DSP.
- **The Bouncer runs at `entrypoint`**, before JSON parsing, because IP-based
  bot/fraud filtering only needs the connection's source IP (and optionally
  `X-Forwarded-For`) — paying the JSON-unmarshal cost for traffic you're
  about to drop wastes the exact latency budget you're trying to protect.
- **The Enricher runs at `raw_auction_request`**, right after parsing, before
  stored-request merge or bidder fan-out — it needs `device.ifa` / `user.id`
  from the parsed body, and it must finish before step 4 above so every DSP
  request (mock or real) gets the decorated payload.
- **Prebid Cache is a second container**, called by PBS after the auction
  resolves, not before — it's on the response path, not the request path.

---

## 4. The pre-bid pipeline: Bouncer + Enricher

Both are implemented as real Prebid Server **Hooks/Modules** — this is the
actual, documented PBS extension mechanism (not a bolt-on proxy), with one
hard constraint worth internalizing up front: **PBS Go modules are compiled
into the binary, not dynamically loaded at runtime.** There's no plugin
directory to drop a `.so` into. Adding a module means vendoring its code
under `modules/<vendor>/<name>/module.go`, running the codegen that wires it
into `modules/builder.go`, and building a custom PBS binary from source —
which is why this repo now needs a custom Dockerfile instead of the stock
`prebid/prebid-server` image (see §5).

### B. Security & bid filtering — the Bouncer

- **Stage:** `entrypoint` (fastest available hook point — pre-JSON-parse).
- **Tech:** an in-process Bloom filter, seeded at startup from a configured
  list of known-bad IPs/device IDs. A Bloom filter is the right structure
  here specifically because a "no" answer is exact and O(1) against an
  in-memory bit array — no database round-trip on the hot path — while a
  "maybe" answer (the filter's only false-positive mode) can fall back to a
  slower authoritative check or just be treated as "block," depending on how
  aggressive you want to be at the edge. It can never wrongly clear bad
  traffic, only occasionally block traffic it shouldn't (tunable via the
  filter's size/hash-count).
- **What it does here:** checks the request's source IP (and, once parsed,
  optionally `device.ifa`) against the filter; on a hit, the module sets
  `HookResult.Reject = true` with an IAB no-bid reason code, short-circuiting
  the request before it costs anything downstream.
- **Where real systems put this instead/also:** at very high scale, this
  same check often runs one layer earlier, at the CDN/load-balancer (e.g.
  Envoy + a WASM filter, or a dedicated edge service) so blocked traffic
  never opens a connection to the bidding host at all. Keeping it as a PBS
  `entrypoint` module is the right scope for this project — one deployable
  unit — and is still a real production pattern, just not the only layer a
  large-scale exchange would use.

### C. Identity matching & decoration — the Enricher

- **Stage:** `raw_auction_request` (parsed body available, before stored-request
  merge / bidder fan-out).
- **Tech (in production):** Aerospike, Redis Enterprise, or ScyllaDB — an
  in-memory/NoSQL key-value store optimized for single-key point lookups
  (device ID → profile), typically co-located with the bidding host to keep
  the round-trip sub-millisecond.
- **Tech (in this repo):** an in-process mock KV store (a Go map seeded at
  startup from a JSON fixture) standing in for that Aerospike/Redis cluster —
  same interface shape (`Get(deviceID) (Profile, bool)`), swappable for a
  real client later without touching the hook logic.
- **What it does here:** looks up `device.ifa`, and on a hit, decorates the
  request — this repo adds the profile as a `user.data[]` segment provider
  block (the standard OpenRTB place for third-party audience data) rather
  than inventing a bespoke `ext` field, so any real bidder adapter would pick
  it up the normal way. The mutation happens via the hook's `ChangeSet`
  (PBS's documented way for a `raw_auction_request` hook to modify the
  request), so it shows up in `ext.debug.resolvedrequest` in debug mode —
  which is how the integration tests verify it actually ran, since none of
  the mock DSPs otherwise "consume" the enrichment.

### A note on confidence

The Go interfaces referenced here (`hookstage.Entrypoint`,
`hookstage.RawAuctionRequest`, `HookResult[T]`, `ChangeSet[T]`) are from
Prebid Server's documented Hooks framework and match what's published at
`pkg.go.dev/github.com/prebid/prebid-server/v2/hooks/hookstage` and
`docs.prebid.org/prebid-server/developers/add-a-module-go.html`. Exact field
names can drift between PBS versions faster than docs are updated — **before
running `docker compose build`, diff the vendored `hookstage` package in
`go.mod`'s resolved version against what's used in `modules/ortbvast/*` and
adjust field names if the compiler complains.** This is flagged explicitly
rather than presented as verified-working, since the full module source
wasn't fetchable during this session (GitHub raw fetches were blocked).

---

## 5. What changes, concretely

| Area | Change |
|---|---|
| `prebid-server/Dockerfile` (new) | Multi-stage build: clone `prebid/prebid-server`, add `modules/ortbvast/{bouncer,enricher}`, `go generate`, build binary |
| `prebid-server/docker-compose.yml` | Build the custom image instead of pulling `prebid/prebid-server:v4.8.0`; add `prebid-cache` service |
| `prebid-server/pbs.yaml` | `account_required: true`; `hooks.enabled` + `host_execution_plan` wiring the two modules; `cache:` block pointing at the new service |
| `prebid-server/stored_requests/data/by_id/accounts/*.json` (new) | One account per STV publisher (FlexTechAds, CircuitTV) with distinct floors/targeting defaults |
| `prebid-server/stored_requests/data/by_id/stored_responses/*.json` | Extended so each imp carries 2–3 competing DSP seats instead of one |
| `examples/*.json` (new) | A second publisher's request fixtures (different device/app) |
| `tests/` (new) | pytest suite replacing/augmenting the manual curl recipes in `TESTING.md` |

See `TESTING.md` for how to exercise all of this once it's running, and
`prebid-server/README-build.md` for the build/verification steps for the
custom image.

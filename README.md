# ortb-vast

Hand-crafted OpenRTB video bid request/response examples for CTV (connected TV)
header bidding, plus a local Prebid Server test harness for validating them
against a real auction/response pipeline without needing a live bidder.

## What's here

### `examples/`

- **`flextechads-ortb-request.json`** — a spec-shaped OpenRTB 2.5/2.6 `BidRequest`
  for a mock exchange ("FlexTechAds"). Represents a Roku CTV app requesting a
  6-slot in-stream video ad pod (linear, 6-35s, 1080p, VAST 4.0/4.3), each
  impression contestable by both a private marketplace (PMP) deal and the open
  auction floor. Uses GPP (`regs.gpp` / `regs.gpp_sid`) for privacy signaling.
- **`flextechads-ortb-request-pbs-test.json`** — the same request, with each
  impression tagged under `ext.prebid.storedauctionresponse` so it can be
  pointed at Prebid Server's stored-response fixtures (see below) instead of
  a live bidder.

### `docs/`

Reference material (gitignored — not tracked in version control): the
OpenRTB 2.6 and VAST 4.3 specs, the IAB CTV VAST addendum, and the original
unmodified example payloads these mocks were built from.

### `prebid-server/`

A Dockerized [Prebid Server](https://docs.prebid.org/prebid-server/overview/prebid-server-overview.html)
(Go) instance configured to serve **stored auction responses** — a real,
documented PBS testing feature that lets a canned bid response flow through
the actual auction/response pipeline (request validation, GPP-aware privacy
parsing, deal-vs-open-floor logic, VAST/targeting assembly) without calling
any real bidder adapter.

```
prebid-server/
  docker-compose.yml   # runs prebid/prebid-server:v4.8.0
  pbs.yaml              # server config: filesystem-backed stored requests/responses
  start.sh / stop.sh     # bring the stack up/down
  stored_requests/data/by_id/stored_responses/
    flex-resp-imp1.json..3.json   # canned PMP deal win ($10 CPM, dealid set)
    flex-resp-imp4.json..6.json   # canned open-auction win ($12.50 CPM)
```

## Running the Prebid Server harness

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cd prebid-server
./start.sh    # docker compose up -d, waits for /status to go healthy
```

Then send the test request:

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @examples/flextechads-ortb-request-pbs-test.json | python3 -m json.tool
```

You should get back a `BidResponse` with 6 bids: 3 carrying `dealid:
FLEXTECHADS-PMP-DEAL-001` at $10 CPM, 3 without a deal at $12.50 CPM, each
with a VAST `adm`.

```bash
./stop.sh     # docker compose down
```

**Note:** stored-response fixtures are loaded into memory once at server
startup. If you edit a file under `stored_requests/`, restart the stack
(`./stop.sh && ./start.sh`) to pick up the change.

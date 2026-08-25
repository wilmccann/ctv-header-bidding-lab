"""
Ported from TESTING.md's original 'Floor-vs-deal edge case' curl recipe.
"""
from conftest import load_example, seatbids_by_seat


def test_deal_bid_bypasses_general_imp_floor(post_auction):
    """
    imp[0].bidfloor is raised to 20 in this fixture — above both the deal's
    own bidfloor (10) and the stored bid's actual price (10.0) — while the
    deal object itself is left untouched. PBS does not floor-enforce bids
    sourced from ext.prebid.storedauctionresponse, so the deal bid still
    comes through despite being priced below the general imp floor.
    """
    body = load_example("flextechads-ortb-request-pbs-test-floor.json")
    resp = post_auction(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    seats = seatbids_by_seat(data)
    bid = next(b for bids in seats.values() for b in bids if b["impid"] == "1")
    assert bid["price"] == 10.0
    assert bid.get("dealid") == "FLEXTECHADS-PMP-DEAL-001"

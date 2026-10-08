"""
Closes the 'Partial no-bid case' item from TESTING.md's Test Ideas list:
an impression whose demand source returns no bids should come back as a
clean no-bid for that slot, without failing the other impressions in the
same auction.

PBS rejects a request where storedauctionresponse is present on some imps
but not others, so imp 3 can't simply drop it. Instead it points at
flex-resp-imp3-nobid, a stored response whose seat returns an empty bid[].
"""
from conftest import load_example, seatbids_by_seat


def test_partial_no_bid_does_not_fail_whole_auction(post_auction):
    body = load_example("flextechads-ortb-request-pbs-test.json")

    # imp 3's only demand source bids nothing
    body["imp"][2]["ext"]["prebid"]["storedauctionresponse"]["id"] = "flex-resp-imp3-nobid"

    resp = post_auction(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    seats = seatbids_by_seat(data)
    impids_with_bids = {b["impid"] for bids in seats.values() for b in bids}
    assert impids_with_bids == {"1", "2"}, (
        f"expected bids for imp 1 and 2 plus a clean no-bid for imp 3, "
        f"got bids for: {sorted(impids_with_bids)}"
    )

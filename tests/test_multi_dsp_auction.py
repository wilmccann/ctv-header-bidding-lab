"""
Exercises the multi-DSP exchange-matching scenario from ARCHITECTURE.md §2:
three seats (house-dsp, nova-dsp, orbit-dsp) all bid on the same
impression via a stored auction response, PBS keeps every valid bid, and
computes per-impression 'winner' targeting keys for whichever bid actually
ranks highest.
"""
import pytest

from conftest import load_example, seatbids_by_seat, targeting_for


def test_three_dsps_bid_on_flextechads_imp1(post_auction):
    body = load_example("flextechads-ortb-request-pbs-test-multidsp.json")
    resp = post_auction(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    seats = seatbids_by_seat(data)
    for seat in ("house-dsp", "nova-dsp", "orbit-dsp"):
        assert seat in seats, f"expected seat {seat} in response, got {sorted(seats)}"

    prices = {
        seat: next(b["price"] for b in bids if b["impid"] == "1")
        for seat, bids in seats.items()
    }
    assert prices["house-dsp"] == pytest.approx(11.0)
    assert prices["nova-dsp"] == pytest.approx(10.0)
    assert prices["orbit-dsp"] == pytest.approx(9.25)

    # nova-dsp is the only seat carrying the PMP deal on this imp
    nova_bid = next(b for b in seats["nova-dsp"] if b["impid"] == "1")
    assert nova_bid.get("dealid") == "FLEXTECHADS-PMP-DEAL-001"
    for seat in ("house-dsp", "orbit-dsp"):
        bid = next(b for b in seats[seat] if b["impid"] == "1")
        assert "dealid" not in bid, f"{seat} shouldn't carry a dealid: {bid}"


def test_highest_bid_wins_generic_targeting_keys(post_auction):
    """
    PBS doesn't discard losing bids — the ad server/decisioning layer is
    meant to pick the winner from the targeting key-values. This asserts
    the ranking signal itself: house-dsp's $11 open-auction bid beats
    nova-dsp's $10 deal bid and orbit-dsp's $9.25 bid, so house-dsp gets
    the unprefixed hb_bidder/hb_pb keys, while every seat still gets its
    own per-bidder keys, and only nova-dsp's bid carries hb_deal.
    """
    body = load_example("flextechads-ortb-request-pbs-test-multidsp.json")
    resp = post_auction(body)
    data = resp.json()

    winner_targeting = targeting_for(data, impid="1", seat="house-dsp")
    assert winner_targeting.get("hb_bidder") == "house-dsp"
    assert winner_targeting.get("hb_pb") is not None
    assert "hb_deal" not in winner_targeting

    for seat in ("house-dsp", "nova-dsp", "orbit-dsp"):
        t = targeting_for(data, impid="1", seat=seat)
        assert any(k.startswith("hb_pb_") for k in t), (
            f"missing per-bidder hb_pb_* key for {seat}: {t}"
        )

    nova_targeting = targeting_for(data, impid="1", seat="nova-dsp")
    assert nova_targeting.get("hb_deal") == "FLEXTECHADS-PMP-DEAL-001"

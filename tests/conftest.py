"""
Shared fixtures/helpers for the ortb-vast integration suite.

Every test here talks to a live Prebid Server instance — there is no
mocking layer, deliberately: the point of `storedauctionresponse` fixtures
is to exercise PBS's *real* auction/targeting/cache pipeline end to end, the
same way `TESTING.md`'s curl recipes do. Start the harness first:

    cd prebid-server && ./start.sh

Then, from the repo root:

    pip install -r tests/requirements.txt
    pytest tests/
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest
import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"

PBS_URL = os.environ.get("PBS_URL", "http://localhost:8000/openrtb2/auction")
PBS_STATUS_URL = os.environ.get("PBS_STATUS_URL", "http://localhost:8000/status")
CACHE_URL = os.environ.get("PBS_CACHE_URL", "http://localhost:2424/cache")


@pytest.fixture(scope="session", autouse=True)
def _require_harness_running():
    try:
        resp = requests.get(PBS_STATUS_URL, timeout=2)
        resp.raise_for_status()
    except requests.RequestException as exc:
        pytest.fail(
            f"Prebid Server isn't responding at {PBS_STATUS_URL} ({exc}).\n"
            f"Start the harness first: cd prebid-server && ./start.sh",
            pytrace=False,
        )


def load_example(filename: str) -> dict:
    with open(EXAMPLES_DIR / filename) as f:
        return json.load(f)


@pytest.fixture
def post_auction():
    def _post(body: dict, headers: dict | None = None) -> requests.Response:
        return requests.post(PBS_URL, json=body, headers=headers, timeout=10)

    return _post


def seatbids_by_seat(response_json: dict) -> dict[str, list[dict]]:
    """{'house-dsp': [bid, ...], 'nova-dsp': [...]} merged across all
    seatbid entries for that seat (PBS can return multiple seatbid objects
    for the same seat)."""
    out: dict[str, list[dict]] = {}
    for sb in response_json.get("seatbid", []):
        out.setdefault(sb["seat"], []).extend(sb.get("bid", []))
    return out


def targeting_for(response_json: dict, impid: str, seat: str | None = None) -> dict:
    """ext.prebid.targeting for the bid matching impid (and seat, if given)."""
    for sb in response_json.get("seatbid", []):
        if seat is not None and sb["seat"] != seat:
            continue
        for bid in sb.get("bid", []):
            if bid.get("impid") == impid:
                return bid.get("ext", {}).get("prebid", {}).get("targeting", {})
    return {}

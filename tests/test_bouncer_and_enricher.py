"""
Exercises the pre-bid pipeline from ARCHITECTURE.md §4: the Bouncer
(entrypoint-stage bad-IP bloom filter) and the Enricher (raw_auction_request
-stage identity decoration). Both modules are new/custom (modules/ortbvast/
{bouncer,enricher}/module.go) — see that file's "NOTE ON PROVENANCE" comment
for what's confirmed against Prebid Server's docs vs. assumed. These tests
are the fastest way to find out, once the custom image is actually running,
whether the assumptions held.
"""
import requests

from conftest import PBS_URL, load_example

# Matches an entry in prebid-server/cache-config/bouncer-blocklist.txt
BLOCKED_IP = "192.0.2.66"

# Matches a key in prebid-server/cache-config/enricher-profiles.json, and
# device.ifa in examples/flextechads-ortb-request-pbs-test-debug.json
ENRICHED_IFA = "8a3f1e2d-0000-4000-8000-000000000001"


def test_bouncer_blocks_known_bad_ip():
    """
    The Bouncer checks the HTTP request's source IP (preferring
    X-Forwarded-For), not any field inside the JSON body — so a perfectly
    valid auction request sent with a blocklisted forwarded-for header
    should be rejected before the auction ever runs.

    STATUS-CODE CAVEAT: exactly what a Reject=true entrypoint hook returns
    (a 4xx, or a 200 with no seatbid) wasn't verifiable against live PBS
    behavior during authoring. Tighten this assertion to the real status
    code once you've run it against the built image.
    """
    body = load_example("flextechads-ortb-request-pbs-test.json")
    resp = requests.post(
        PBS_URL,
        json=body,
        headers={"X-Forwarded-For": BLOCKED_IP},
        timeout=10,
    )
    blocked = resp.status_code >= 400 or not resp.json().get("seatbid")
    assert blocked, (
        f"expected the Bouncer to reject a request from a blocklisted IP "
        f"({BLOCKED_IP}), got {resp.status_code}: {resp.text[:500]}"
    )


def test_bouncer_allows_clean_ip(post_auction):
    """Sanity check that the Bouncer isn't just blocking everything."""
    body = load_example("flextechads-ortb-request-pbs-test.json")
    resp = post_auction(body, headers={"X-Forwarded-For": "203.0.113.42"})
    assert resp.status_code == 200, resp.text
    assert resp.json().get("seatbid")


def test_enricher_decorates_known_device(post_auction):
    """
    device.ifa 8a3f1e2d-... is seeded with segments in
    cache-config/enricher-profiles.json. The Enricher runs before
    stored-request merge / bidder fan-out, so its mutation should be
    visible in ext.debug.resolvedrequest under debug mode — the only way
    to observe it here, since none of the mock DSP stored responses
    actually consume the enrichment themselves.
    """
    body = load_example("flextechads-ortb-request-pbs-test-debug.json")
    assert body["device"]["ifa"] == ENRICHED_IFA  # keep fixture + test in sync

    resp = post_auction(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    resolved = data.get("ext", {}).get("debug", {}).get("resolvedrequest", {})
    user_data = resolved.get("user", {}).get("data", [])
    providers = [d.get("name") for d in user_data]
    assert "ortbvast-mock-idsp" in providers, (
        f"expected the Enricher's segment-provider block in resolved "
        f"user.data, got: {user_data}"
    )

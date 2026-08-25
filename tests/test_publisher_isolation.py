"""
Multi-tenancy: two STV publishers on the same PBS instance, resolved to
different accounts with different config (ARCHITECTURE.md §3/§5).
"""
from conftest import load_example, targeting_for


def test_circuittv_uses_its_own_targeting_prefix(post_auction):
    """
    circuit-pub-001's account file sets targeting_prefix: 'ctv_';
    flex-pub-001 keeps PBS's default 'hb_' prefix. This is the concrete,
    testable signal that account-level config actually isolates one
    publisher's behavior from another's — see
    prebid-server/stored_requests/data/by_id/accounts/*.json.
    """
    body = load_example("circuittv-ortb-request-pbs-test.json")
    resp = post_auction(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    targeting = targeting_for(data, impid="1", seat="house-dsp")
    assert targeting, "expected targeting keys on circuit-pub-001's imp 1"
    assert all(k.startswith("ctv_") for k in targeting), targeting
    assert not any(k.startswith("hb_") for k in targeting), targeting


def test_unregistered_publisher_is_rejected(post_auction):
    """account_required: true means a publisher ID with no accounts/<id>.json
    on file must be rejected outright, not silently given global defaults."""
    body = load_example("circuittv-ortb-request-pbs-test.json")
    body["app"]["publisher"]["id"] = "unregistered-pub-999"

    resp = post_auction(body)
    assert resp.status_code >= 400, (
        f"expected an error for an unregistered account, "
        f"got {resp.status_code}: {resp.text[:500]}"
    )

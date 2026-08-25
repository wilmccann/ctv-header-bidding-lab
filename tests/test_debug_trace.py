"""
Ported from TESTING.md's original 'Debug-mode trace' curl recipe.
"""
from conftest import load_example


def test_debug_mode_returns_resolved_request(post_auction):
    body = load_example("flextechads-ortb-request-pbs-test-debug.json")
    resp = post_auction(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    debug = data.get("ext", {}).get("debug", {})
    assert "resolvedrequest" in debug, (
        "expected ext.debug.resolvedrequest in a debug-mode response"
    )
    resolved = debug["resolvedrequest"]
    assert resolved.get("ext", {}).get("prebid", {}).get("debug") is True

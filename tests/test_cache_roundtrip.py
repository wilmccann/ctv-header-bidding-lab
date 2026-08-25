"""
Closes the 'Cache round-trip' item from TESTING.md's Test Ideas list, now
that the prebid-cache service exists (docker-compose.yml) and pbs.yaml has
a cache: block. Confirms ext.prebid.cache.vastxml on the request produces
a hb_cache_id targeting key, and that GET /cache?uuid=<id> returns VAST
matching what the stored-response fixture defined.
"""
import requests

from conftest import CACHE_URL, load_example, targeting_for


def test_vast_cache_roundtrip(post_auction):
    body = load_example("flextechads-ortb-request-pbs-test-multidsp.json")
    resp = post_auction(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    targeting = targeting_for(data, impid="1", seat="house-dsp")
    cache_id = targeting.get("hb_cache_id") or targeting.get("hb_uuid")
    assert cache_id, f"expected hb_cache_id/hb_uuid in targeting: {targeting}"

    cache_resp = requests.get(CACHE_URL, params={"uuid": cache_id}, timeout=10)
    assert cache_resp.status_code == 200, cache_resp.text
    assert b"<VAST" in cache_resp.content
    assert b"house-dsp.example" in cache_resp.content

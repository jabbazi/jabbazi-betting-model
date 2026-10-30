import httpx
from jabazi.providers.balldontlie import BallDontLieProvider


def test_nhl_probe_success_does_not_claim_full_coverage():
    def handler(request):
        assert request.url.path == "/nhl/v1/odds/player_props"
        assert request.url.params["game_id"] == "123"
        return httpx.Response(200, json={"data": [{"id": 1}], "meta": {}})
    p = BallDontLieProvider("test", transport=httpx.MockTransport(handler), interval=0)
    try:
        assert p.probe_nhl_props(123) == {
            "sport": "nhl", "status": "AVAILABLE", "rows": 1,
            "entitlement_verified": True, "full_slate_verified": False,
        }
    finally:
        p.close()


def test_nhl_probe_unauthorized():
    p = BallDontLieProvider("test", transport=httpx.MockTransport(
        lambda request: httpx.Response(401)), interval=0)
    try:
        result = p.probe_nhl_props(123)
        assert result["error"] == "HTTP_401"
        assert result["entitlement_verified"] is False
    finally:
        p.close()

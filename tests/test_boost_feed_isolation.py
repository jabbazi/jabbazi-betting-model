"""Sport-isolation tests for the read-only boost feed."""
import httpx
from jabazi.boost_scope import BoostScope
from jabazi.boost_feed import collect_boost_odds
from jabazi.providers.balldontlie import BallDontLieProvider


def test_nhl_boost_uses_nhl_endpoint_only():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": 1}], "meta": {}})
    provider = BallDontLieProvider("test", transport=httpx.MockTransport(handler), interval=0)
    try:
        result = collect_boost_odds(provider, BoostScope("icehockey_nhl"), game_ids=[123])
        assert result.coverage == "FULL"
        assert result.odds_rows == 1
        assert paths == ["/nhl/v1/odds/player_props"]
    finally:
        provider.close()

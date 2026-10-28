"""Sport-isolation and integrity tests for read-only paid-odds acquisition."""
import httpx

from jabazi.boost_scope import BoostScope
from jabazi.boost_feed import collect_boost_odds
from jabazi.providers.balldontlie import BallDontLieProvider


def test_nhl_boost_uses_nhl_endpoint_only():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={
            "data": [{"id": 1, "game_id": 123}], "meta": {},
        })

    provider = BallDontLieProvider(
        "test", transport=httpx.MockTransport(handler), interval=0,
    )
    try:
        result = collect_boost_odds(
            provider, BoostScope("icehockey_nhl"), game_ids=[123],
        )
        assert result.coverage == "FULL"
        assert result.odds_rows == 1
        assert result.raw_odds_rows == 1
        assert result.game_row_counts == ((123, 1),)
        assert paths == ["/nhl/v1/odds/player_props"]
    finally:
        provider.close()


def test_duplicate_and_foreign_game_rows_fail_closed():
    def handler(request):
        return httpx.Response(200, json={
            "data": [
                {"id": 4, "game_id": 123},
                {"id": 4, "game_id": 123},
                {"id": 5, "game_id": 999},
                {"id": None, "game_id": 123},
            ], "meta": {},
        })

    provider = BallDontLieProvider(
        "test", transport=httpx.MockTransport(handler), interval=0,
    )
    try:
        result = collect_boost_odds(
            provider, BoostScope("icehockey_nhl"), game_ids=[123],
        )
        assert result.coverage == "PARTIAL"
        assert result.games_succeeded == 1
        assert result.odds_rows == 1
        assert result.raw_odds_rows == 4
        assert result.duplicate_rows == 1
        assert result.mismatched_game_rows == 1
        assert result.invalid_rows == 1
        assert result.game_row_counts == ((123, 1),)
        assert "DUPLICATE_PROP_IDENTITIES" in result.errors
        assert "FOREIGN_GAME_PROP_IDENTITIES" in result.errors
    finally:
        provider.close()


def test_empty_provider_response_is_not_calibration():
    def handler(request):
        return httpx.Response(200, json={"data": [], "meta": {}})

    provider = BallDontLieProvider(
        "test", transport=httpx.MockTransport(handler), interval=0,
    )
    try:
        result = collect_boost_odds(
            provider, BoostScope("basketball_nba"), game_ids=[456],
        )
        assert result.odds_rows == 0
        assert result.coverage == "FULL"
        assert result.rows == ()
    finally:
        provider.close()

"""Sport-isolation, live quote integrity and provenance tests."""
from datetime import UTC, datetime

import httpx

from jabazi.boost_scope import BoostScope
from jabazi.boost_feed import collect_boost_odds
from jabazi.providers.balldontlie import BallDontLieProvider


def quote(identifier, game_id, *, player_id=12, prop_type="goals"):
    return {
        "id": identifier, "game_id": game_id,
        "player_id": player_id, "vendor": "draftkings",
        "prop_type": prop_type, "line_value": "0.5",
        "market": {"type": "over_under",
                   "over_odds": 130, "under_odds": -150},
        "updated_at": datetime.now(UTC).isoformat(),
    }


def test_nhl_boost_uses_nhl_endpoint_only():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={
            "data": [quote(1, 123)], "meta": {},
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
                quote(4, 123),
                quote(999, 123),  # same semantic offer, refreshed vendor ID
                quote(5, 999),
                quote(None, 123),
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


def test_promo_market_scope_rejects_unrelated_props_without_overscanning():
    provider = BallDontLieProvider("test", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={
            "data": [quote(1, 123), quote(2, 123, prop_type="shots_on_goal")],
            "meta": {},
        })), interval=0)
    try:
        result = collect_boost_odds(
            provider, BoostScope("icehockey_nhl",
                                 markets=frozenset({"goals"})),
            game_ids=[123],
        )
        assert result.odds_rows == 1
        assert result.out_of_scope_rows == 1
        assert result.coverage == "FULL"
    finally:
        provider.close()


def test_empty_provider_response_is_not_calibration():
    provider = BallDontLieProvider("test", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={
            "data": [], "meta": {},
        })), interval=0)
    try:
        result = collect_boost_odds(
            provider, BoostScope("basketball_nba"), game_ids=[456],
        )
        assert result.odds_rows == 0
        assert result.coverage == "FULL"
        assert result.rows == ()
    finally:
        provider.close()

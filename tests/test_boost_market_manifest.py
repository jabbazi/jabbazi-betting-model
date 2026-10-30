"""Provider-listed priority market observations are not provider coverage proof."""
import pytest

from jabazi.boost_market_manifest import (
    PRIORITY_MARKETS, audit_priority_market_presence,
)


def observed():
    return {
        "markets": {
            "points": {"games_with_market": 2, "accepted_quote_rows": 40},
            "points_rebounds_assists": {
                "games_with_market": 1, "accepted_quote_rows": 6,
            },
        },
        "status": "OBSERVED_ONLY",
    }


def test_nba_points_observed_and_pra_missing_in_one_game():
    audit = audit_priority_market_presence(
        "NBA", observed(), eligible_games=2,
    )
    by_type = {x["prop_type"]: x for x in audit["categories"]}
    assert by_type["points"]["games_without_observed_quote"] == 0
    assert by_type["points_rebounds_assists"]["games_without_observed_quote"] == 1
    assert by_type["rebounds"]["observation"] == "NOT_OBSERVED"
    assert audit["priority_markets_observed"] == 2
    assert audit["priority_market_count"] == len(PRIORITY_MARKETS["NBA"])
    assert audit["source_defined_market_universe_complete"] is False
    assert audit["executable_parlay_quote_verified"] is False


def test_nhl_first_goal_is_tracked_without_inventory_completeness_claim():
    a = audit_priority_market_presence(
        "NHL", {"markets": {"goals": {
            "games_with_market": 1, "accepted_quote_rows": 4,
        }}}, eligible_games=1,
    )
    first_goal = next(x for x in a["categories"] if x["prop_type"] == "first_goal")
    assert first_goal["observation"] == "NOT_OBSERVED"
    assert first_goal["games_without_observed_quote"] == 1
    assert a["status"] == "OBSERVATIONAL_RESEARCH_ONLY"


def test_nfl_known_1h_market_absence_is_not_a_failed_entitlement():
    a = audit_priority_market_presence(
        "NFL", {"markets": {}}, eligible_games=1,
    )
    assert a["priority_markets_observed"] == 0
    assert all(x["observation"] == "NOT_OBSERVED" for x in a["categories"])
    assert not a["every_player_and_book_verified"]


def test_no_game_has_no_fake_priority_market_coverage():
    a = audit_priority_market_presence(
        "NBA", {"markets": {}}, eligible_games=0,
    )
    assert a["eligible_games"] == 0
    assert a["priority_markets_observed"] == 0
    assert a["categories"][0]["games_without_observed_quote"] == 0


@pytest.mark.parametrize("sport,games", [
    ("MLB", 1), ("nba", 1), ("NBA", -1), ("NBA", True),
])
def test_invalid_sport_or_game_scope_fail_closed(sport, games):
    with pytest.raises(ValueError):
        audit_priority_market_presence(
            sport, {"markets": {}}, eligible_games=games,
        )


@pytest.mark.parametrize("counts", [
    {"games_with_market": 3, "accepted_quote_rows": 3},
    {"games_with_market": True, "accepted_quote_rows": 3},
    {"games_with_market": -1, "accepted_quote_rows": 3},
    {"games_with_market": 1, "accepted_quote_rows": float("nan")},
])
def test_invalid_observed_counts_never_claim_presence(counts):
    with pytest.raises(ValueError, match="Invalid observed-market game count"):
        audit_priority_market_presence(
            "NBA", {"markets": {"points": counts}}, eligible_games=2,
        )


def test_unknown_vendor_category_not_turned_into_synthetic_market():
    a = audit_priority_market_presence(
        "NBA", {"markets": {
            "private_vendor_market": {"games_with_market": 2, "accepted_quote_rows": 99},
        }}, eligible_games=2,
    )
    assert "private_vendor_market" not in str(a)
    assert a["priority_markets_observed"] == 0

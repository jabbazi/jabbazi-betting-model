import pytest

from jabazi.boost_goat_model_map import GOAT_TO_JABBAZI, summarize_goat_model_market_alignment
from jabazi.models.player_distribution import PLAYER_PROP_MARKETS
from jabazi.boost_scope import SPORTS


@pytest.mark.parametrize("sport", ["NBA", "NFL", "NHL"])
def test_every_mapped_category_is_a_real_jabbazi_player_model_market(sport):
    assert GOAT_TO_JABBAZI[sport]
    assert set(GOAT_TO_JABBAZI[sport].values()).issubset(PLAYER_PROP_MARKETS[SPORTS[sport]])


@pytest.mark.parametrize("sport,source,model", [
    ("NBA", "points", "player_points"),
    ("NBA", "points_rebounds_assists", "player_points_rebounds_assists"),
    ("NFL", "passing_yards", "player_pass_yds"),
    ("NFL", "receiving_yards", "player_reception_yds"),
    ("NHL", "shots_on_goal", "player_shots_on_goal"),
    ("NHL", "saves", "player_total_saves"),
])
def test_sport_specific_documented_market_mapping(sport, source, model):
    report = summarize_goat_model_market_alignment(sport, {
        "markets": {source: {"accepted_quote_rows": 17}},
    })
    assert report["categories"][0]["jabbazi_market"] == model
    assert report["mapped_quote_rows"] == 17
    assert report["model_hit_probability_verified"] is False
    assert report["betting_enabled"] is False


@pytest.mark.parametrize("sport,source", [
    ("NBA", "first_basket"),
    ("NFL", "first_td"),
    ("NFL", "rushing_receiving_yards"),
    ("NHL", "first_goal"),
    ("NHL", "anytime_goal"),
])
def test_unmapped_market_never_invents_model_support(sport, source):
    report = summarize_goat_model_market_alignment(sport, {
        "markets": {source: {"accepted_quote_rows": 3}},
    })
    assert report["categories"][0]["jabbazi_market"] is None
    assert report["unmapped_quote_rows"] == 3
    assert report["mapped_quote_rows"] == 0


def test_same_market_label_maps_by_sport_not_global_name():
    nba = summarize_goat_model_market_alignment("NBA", {
        "markets": {"points": {"accepted_quote_rows": 2}},
    })
    nhl = summarize_goat_model_market_alignment("NHL", {
        "markets": {"points": {"accepted_quote_rows": 5}},
    })
    assert nba["sport"] == "NBA" and nhl["sport"] == "NHL"
    assert nba["mapped_quote_rows"] == 2 and nhl["mapped_quote_rows"] == 5


def test_invalid_counts_and_sports_fail_closed():
    with pytest.raises(ValueError):
        summarize_goat_model_market_alignment("MLB", {"markets": {}})
    with pytest.raises(ValueError):
        summarize_goat_model_market_alignment("NBA", {"markets": {"points": {"accepted_quote_rows": True}}})
    with pytest.raises(ValueError):
        summarize_goat_model_market_alignment("NBA", {"markets": {"points": {"accepted_quote_rows": -1}}})
    with pytest.raises(ValueError):
        summarize_goat_model_market_alignment("NBA", {"markets": None})


def test_alignment_does_not_claim_any_player_identity_or_artifact_approval():
    report = summarize_goat_model_market_alignment("NHL", {
        "markets": {"goals": {"accepted_quote_rows": 50}},
    })
    assert report["specific_player_game_identity_verified"] is False
    assert report["fresh_pregame_feature_snapshot_verified"] is False
    assert report["model_artifact_and_version_verified"] is False
    assert report["joint_probability_verified"] is False
    assert report["approval"] == "RESEARCH_ONLY"

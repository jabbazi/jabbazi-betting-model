from datetime import UTC, datetime, timedelta

import pytest

from jabazi.boost_goat_feature_join import audit_exact_model_inputs

NOW = datetime(2026, 10, 29, 21, 0, tzinfo=UTC)
STAMP = (NOW - timedelta(minutes=2)).isoformat()
FROZEN = (NOW - timedelta(hours=2)).isoformat()


def feature(**kw):
    row = {"sport": "NBA", "bdl_game_id": 77, "bdl_player_id": 19,
           "jabbazi_market": "player_points", "line": 22.5,
           "model_version": "nba-points-v3", "feature_frozen_at": FROZEN,
           "provider_identity_verified": True, "pregame_snapshot_verified": True}
    row.update(kw)
    return row


def offer(**kw):
    row = {"game_id": 77, "player_id": 19, "prop_type": "points",
           "line_value": 22.5, "vendor": "testbook", "updated_at": STAMP}
    row.update(kw)
    return {"sport": "basketball_nba", "raw": row}


def audit(features, offers, sport="NBA"):
    return audit_exact_model_inputs(sport, offers, features, observed_at=NOW)


def test_exact_versioned_join_is_not_a_probability():
    result = audit([feature()], [offer()])
    assert result["exact_versioned_input_matches"] == 1
    assert result["model_probability_computed"] is False
    assert result["model_calibration_verified"] is False
    assert result["betting_enabled"] is False


@pytest.mark.parametrize("change", [
    {"game_id": 78}, {"player_id": 20}, {"prop_type": "rebounds"},
    {"line_value": 23.5}, {"updated_at": (NOW-timedelta(hours=1)).isoformat()},
])
def test_mismatched_or_stale_offer_is_not_joined(change):
    assert audit([feature()], [offer(**change)])["exact_versioned_input_matches"] == 0


@pytest.mark.parametrize("change", [
    {"provider_identity_verified": False},
    {"pregame_snapshot_verified": False},
    {"model_version": ""},
    {"bdl_player_id": None},
    {"line": None},
    {"feature_frozen_at": "bad"},
    {"feature_frozen_at": (NOW + timedelta(minutes=1)).isoformat()},
])
def test_missing_model_provenance_rejected(change):
    result = audit([feature(**change)], [offer()])
    assert result["exact_versioned_input_matches"] == 0


def test_duplicate_feature_records_rejected():
    result = audit([feature(), feature()], [offer()])
    assert result["exact_versioned_input_matches"] == 0
    assert result["rejections"]["ambiguous_feature_records"] == 1


def test_duplicate_vendor_offer_not_double_counted():
    result = audit([feature()], [offer(), offer()])
    assert result["exact_versioned_input_matches"] == 1
    assert result["rejections"]["duplicate_offer"] == 1


def test_no_names_or_vendor_rows_exposed():
    result = audit([feature(player_name="PRIVATE_PLAYER")], [offer(vendor="PRIVATE_BOOK")])
    assert "PRIVATE_PLAYER" not in str(result)
    assert "PRIVATE_BOOK" not in str(result)


def test_nfl_uses_its_own_market_map():
    nfl_feature = feature(sport="NFL", jabbazi_market="player_pass_yds")
    nfl_offer = {"sport": "americanfootball_nfl", "raw": {
        "game_id": 77, "player_id": 19, "prop_type": "passing_yards",
        "line_value": 22.5, "vendor": "testbook", "updated_at": STAMP}}
    assert audit([nfl_feature], [nfl_offer], "NFL")["exact_versioned_input_matches"] == 1


def test_unsupported_sport_rejected():
    with pytest.raises(ValueError):
        audit([], [], "MLB")

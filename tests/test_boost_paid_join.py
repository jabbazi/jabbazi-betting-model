from datetime import UTC, datetime, timedelta

import pytest

from jabazi.boost_paid_join import reconcile_paid_player_research


NOW = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)
STAMP = (NOW - timedelta(minutes=2)).isoformat()


def lab(**updates):
    row = dict(sport="NBA", game_id=31, player_id=8, market="points",
               market_line=24.5, created_at=STAMP,
               hit_probability_verified=False, model_hit_probability=None)
    row.update(updates)
    return row


def odds(**updates):
    row = dict(game_id=31, player_id=8, prop_type="points",
               line_value=24.5, updated_at=STAMP)
    row.update(updates)
    return {"sport": "basketball_nba", "raw": row}


def check(labs, offers, sport="NBA"):
    return reconcile_paid_player_research(sport, labs, offers, observed_at=NOW)


def test_exact_identity_join_is_research_only():
    result = check([lab()], [odds()])
    assert result["unique_exact_identity_joins"] == 1
    assert result["identity_namespace_independently_verified"] is False
    assert result["calibrated_exact_line_hit_probabilities_verified"] is False
    assert result["joint_probability_validated"] is False
    assert result["betting_enabled"] is False


@pytest.mark.parametrize("change", [
    {"game_id": 32}, {"player_id": 9}, {"prop_type": "rebounds"},
    {"line_value": 25.5}, {"updated_at": "2026-10-27T20:00:00Z"},
    {"updated_at": "not-a-timestamp"},
])
def test_rejects_mismatched_or_stale_sportsbook_offer(change):
    result = check([lab()], [odds(**change)])
    assert result["unique_exact_identity_joins"] == 0


def test_rejects_ambiguous_lab_predictions():
    result = check([lab(), lab()], [odds()])
    assert result["unique_exact_identity_joins"] == 0
    assert result["rejections"]["lab_ambiguous_exact_identity"] == 1


def test_rejects_lab_probability_claim():
    result = check([lab(model_hit_probability=.9)], [odds()])
    assert result["unique_exact_identity_joins"] == 0
    assert result["rejections"]["lab_unverified_probability_claim"] == 1


def test_rejects_lab_missing_line_and_identity():
    result = check([lab(market_line=None), lab(player_id=None)], [odds()])
    assert result["unique_exact_identity_joins"] == 0
    assert result["rejections"]["lab_missing_exact_identity_or_line"] == 2


def test_nhl_lab_prop_join_not_supported():
    with pytest.raises(ValueError):
        check([lab(sport="NHL")], [odds()], sport="NHL")


def test_no_proprietary_rows_returned():
    result = check([lab(player_name="PRIVATE_PLAYER")], [odds(vendor="PRIVATE_BOOK")])
    assert "PRIVATE_PLAYER" not in str(result)
    assert "PRIVATE_BOOK" not in str(result)

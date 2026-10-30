from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tools import verify_goat_feature_join as probe

NOW = datetime(2026, 10, 29, 21, 0, tzinfo=UTC)
STAMP = (NOW - timedelta(minutes=2)).isoformat()
FROZEN = (NOW - timedelta(hours=2)).isoformat()


def feature():
    return {"sport": "NBA", "bdl_game_id": 77, "bdl_player_id": 19,
            "jabbazi_market": "player_points", "line": 22.5,
            "model_version": "nba-v3", "feature_frozen_at": FROZEN,
            "provider_identity_verified": True, "pregame_snapshot_verified": True,
            "player_name": "PRIVATE_PLAYER"}


def quote():
    return {"sport": "basketball_nba", "raw": {
        "game_id": 77, "player_id": 19, "prop_type": "points",
        "line_value": 22.5, "vendor": "PRIVATE_BOOK", "updated_at": STAMP}}


def test_complete_paid_feed_with_exact_feature_join_still_research_only(monkeypatch):
    monkeypatch.setattr(probe, "collect_boost_odds", lambda provider, scope, **kwargs:
        SimpleNamespace(coverage="FULL", odds_rows=1, rows=(quote(),)))
    report = probe.audit_private_feature_join("NBA", [77], [feature()],
                                              provider=object(), observed_at=NOW)
    assert report["exact_versioned_input_matches"] == 1
    assert report["status"] == "RESEARCH_ONLY"
    assert report["model_probability_computed"] is False
    assert report["production_approved"] is False
    assert "PRIVATE_PLAYER" not in str(report)
    assert "PRIVATE_BOOK" not in str(report)


def test_incomplete_feed_blocks_feature_join(monkeypatch):
    monkeypatch.setattr(probe, "collect_boost_odds", lambda provider, scope, **kwargs:
        SimpleNamespace(coverage="PARTIAL", odds_rows=1, rows=(quote(),)))
    report = probe.audit_private_feature_join("NFL", [77], [],
                                              provider=object(), observed_at=NOW)
    assert report["exact_versioned_input_matches"] == 0
    assert report["reason"] == "INCOMPLETE_OR_EMPTY_PAID_PROP_COVERAGE"


@pytest.mark.parametrize("sport,ids", [("NHL", [77]), ("NBA", []),
                                        ("NBA", [77, 77]), ("NFL", [0])])
def test_invalid_scope_fails_before_any_paid_request(sport, ids):
    with pytest.raises(ValueError):
        probe.audit_private_feature_join(sport, ids, [], provider=object(),
                                         observed_at=NOW)

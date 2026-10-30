"""Private paid-join operator diagnostic must fail closed and redact data."""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from tools import verify_paid_join as probe


DAY = date(2026, 10, 28)


def test_missing_distinct_lab_key_does_not_query_any_provider():
    result = probe.run(
        sport="NBA", slate_date=DAY, game_ids=[31],
        settings=SimpleNamespace(balldontlie_api_key="sports", balldontlie_lab_api_key=""),
        lab_reader=lambda *a: (_ for _ in ()).throw(AssertionError("LAB queried")),
        provider_factory=lambda *a, **k: (_ for _ in ()).throw(AssertionError("odds queried")),
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "MISSING_CREDENTIALS"
    assert result["betting_enabled"] is False


def test_empty_lab_never_queries_sportsbook():
    result = probe.run(
        sport="NFL", slate_date=DAY, game_ids=[42],
        settings=SimpleNamespace(balldontlie_api_key="sports", balldontlie_lab_api_key="lab"),
        lab_reader=lambda *a: {"state": "NO_PREDICTIONS", "coverage_complete": True, "rows": []},
        provider_factory=lambda *a, **k: (_ for _ in ()).throw(AssertionError("odds queried")),
    )
    assert result["lab_authenticated"] is True
    assert result["sports_api_complete"] is False
    assert result["reason"] == "LAB_ACCESS_OR_PREDICTIONS_UNVERIFIED"


def test_valid_exact_join_is_still_not_calibrated_or_betting_approved(monkeypatch):
    now = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    lab = {
        "sport": "NBA", "game_id": 31, "player_id": 8,
        "market": "points", "market_line": 24.5, "created_at": now,
        "model_hit_probability": None, "hit_probability_verified": False,
        "player_name": "PRIVATE_PLAYER",
    }
    offer = {
        "sport": "basketball_nba",
        "raw": {"game_id": 31, "player_id": 8, "prop_type": "points",
                "line_value": 24.5, "updated_at": now, "vendor": "PRIVATE_BOOK"},
    }
    class Provider:
        def __init__(self, key, **kwargs):
            assert key == "sports-only"
        def close(self):
            pass
    def fake_collect(provider, scope, **kwargs):
        assert kwargs["game_ids"] == [31]
        return SimpleNamespace(coverage="FULL", odds_rows=1, rows=(offer,))
    monkeypatch.setattr(probe, "collect_boost_odds", fake_collect)
    report = probe.run(
        sport="NBA", slate_date=DAY, game_ids=[31],
        settings=SimpleNamespace(balldontlie_api_key="sports-only", balldontlie_lab_api_key="lab-only"),
        lab_reader=lambda key, sport, day: {
            "state": "RESEARCH_ONLY", "coverage_complete": True, "rows": [lab]
        },
        provider_factory=Provider,
    )
    assert report["status"] == "RESEARCH_ONLY"
    assert report["exact_identity_joins"] == 1
    assert report["identity_namespace_independently_verified"] is False
    assert report["calibrated_exact_line_hit_probabilities_verified"] is False
    assert report["joint_probability_validated"] is False
    assert report["betting_enabled"] is False
    assert report["production_approved"] is False
    assert "PRIVATE_PLAYER" not in str(report)
    assert "PRIVATE_BOOK" not in str(report)


def test_invalid_or_duplicate_game_ids_fail_before_calls():
    import pytest
    for ids in ([], [31, 31], [0], [-1], [True], list(range(1, 7))):
        with pytest.raises(ValueError):
            probe.run(sport="NBA", slate_date=DAY, game_ids=ids)

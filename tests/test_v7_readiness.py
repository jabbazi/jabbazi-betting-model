"""V7 readiness is a read-only preflight, never an approval mechanism."""
from datetime import UTC, datetime
from types import SimpleNamespace
import pytest
from jabazi.paid_readiness import summarize_readiness

NOW = datetime(2026, 11, 9, 6, tzinfo=UTC)


def models():
    return {("basketball_nba", "player_points"): SimpleNamespace(stage="VALIDATING"),
            ("americanfootball_nfl", "player_receptions"): SimpleNamespace(stage="VALIDATING"),
            ("icehockey_nhl", "player_shots_on_goal"): SimpleNamespace(stage="VALIDATING")}


def test_unregistered_crosswalks_and_stale_features_are_explicit():
    result = summarize_readiness(models(), {}, {}, observed_at=NOW)
    for sport in ("NBA", "NFL", "NHL"):
        row = result["sports"][sport]
        assert row["status"] == "BLOCKED"
        assert "NO_REGISTERED_REVIEWED_IDENTITY_MANIFEST" in row["reasons"]
        assert "NO_RECENT_PLAYER_FEATURE_SNAPSHOTS" in row["reasons"]
        assert row["wagering_approved"] is False
    assert result["provider_requests"] == 0
    assert result["database_writes"] is False


def test_recent_unverified_nfl_does_not_become_verified():
    result = summarize_readiness(models(), {"NFL": 1}, {
        "americanfootball_nfl": {"recent": 9, "recent_verified": 0}
    }, observed_at=NOW)
    row = result["sports"]["NFL"]
    assert row["feature_snapshots_last_24h"] == 9
    assert "NO_RECENT_VERIFIED_PLAYER_FEATURE_SNAPSHOTS" in row["reasons"]
    assert "NO_REGISTERED_REVIEWED_IDENTITY_MANIFEST" not in row["reasons"]


def test_registered_and_recent_still_requires_live_game_review():
    approved = {("basketball_nba", "player_points"):
                SimpleNamespace(stage="PRODUCTION_APPROVED")}
    result = summarize_readiness(approved, {"NBA": 1}, {
        "basketball_nba": {"recent": 2, "recent_verified": 2}
    }, observed_at=NOW)
    row = result["sports"]["NBA"]
    assert row["status"] == "BLOCKED"
    assert row["reasons"] == ["SLATE_IDENTITY_AND_EXACT_LINE_INFERENCE_NOT_AUDITED"]
    assert row["live_exact_line_probability_verified"] is False


def test_invalid_count_or_naive_time_is_rejected():
    with pytest.raises(ValueError):
        summarize_readiness(models(), {}, {}, observed_at=datetime(2026, 11, 9))
    with pytest.raises(ValueError):
        summarize_readiness(models(), {}, {
            "icehockey_nhl": {"recent": 0, "recent_verified": 1}
        }, observed_at=NOW)


def test_no_model_is_never_a_pass():
    row = summarize_readiness({}, {"NHL": 1}, {
        "icehockey_nhl": {"recent": 1, "recent_verified": 1}
    }, observed_at=NOW)["sports"]["NHL"]
    assert "NO_LOADABLE_PLAYER_MODELS" in row["reasons"]

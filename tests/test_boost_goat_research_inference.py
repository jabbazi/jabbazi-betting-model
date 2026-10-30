from datetime import UTC, datetime, timedelta
from math import log

import pytest

from jabazi.boost_goat_research_inference import research_goat_exact_line
from jabazi.boost_identity_manifest import crosswalk_digest
from jabazi.research.player_features import REQUIRED_INTEGRITY

NOW = datetime(2026, 10, 29, 21, tzinfo=UTC)
START = (NOW + timedelta(hours=2)).isoformat()


def offer(**changes):
    row = {
        "id": 100, "game_id": 77, "player_id": 19,
        "vendor": "PRIVATE_BOOK", "prop_type": "points",
        "line_value": "20.5", "market": {
            "type": "over_under", "over_odds": -110, "under_odds": -110,
        },
        "updated_at": (NOW - timedelta(minutes=1)).isoformat(),
    }
    row.update(changes)
    return row


def crosswalk(**changes):
    row = {
        "sport": "NBA", "bdl_game_id": 77, "bdl_player_id": 19,
        "source_namespace": "ESPN", "source_player_id": "PRIVATE_ESPN_ID",
        "source_record_sha256": "a" * 64,
        "canonical_event_id": "PRIVATE_EVENT",
        "event_starts_at": START,
        "reviewed_at": (NOW - timedelta(minutes=15)).isoformat(),
        "independent_source_reviewed": True,
    }
    row.update(changes)
    row["record_sha256"] = crosswalk_digest(row)
    return row


def snapshot(**changes):
    row = {
        "sport": "basketball_nba", "event_id": "PRIVATE_EVENT",
        "player_id": "PRIVATE_ESPN_ID", "market": "player_points",
        "starts_at": START,
        "features_available_at": (NOW - timedelta(minutes=10)).isoformat(),
        "snapshot_id": "playerfs-" + "b" * 20,
        "source_checksum": "c" * 64, "provider": "ESPN",
        "feature_schema_version": "test-v1",
        "integrity": {name: True for name in REQUIRED_INTEGRITY},
        "features": {"games_prior": 10.0},
    }
    row.update(changes)
    return row


def artifact(**changes):
    row = {
        "sport": "basketball_nba", "market": "player_points",
        "artifact_type": "player_prop_distribution", "stage": "VALIDATING",
        "model_version": "nba-test-v1", "family": "count_nb",
        "feature_names": ["games_prior"],
        "scaler": {"mean": [0], "scale": [1]},
        "parameters": {"coef": [0], "intercept": log(20), "dispersion": 0.2},
        "calibration": None, "validation": {"promotion_passed": False},
    }
    row.update(changes)
    return row


def run(raw=None, cw=None, fs=None, model=None):
    return research_goat_exact_line(
        "NBA", offer() if raw is None else raw,
        crosswalk() if cw is None else cw,
        snapshot() if fs is None else fs,
        artifact() if model is None else model, observed_at=NOW,
    )


def test_exact_line_distribution_returns_research_probabilities_not_wager():
    result = run()
    assert result["status"] == "RESEARCH_ONLY"
    assert result["model_version"] == "nba-test-v1"
    assert result["market"] == "player_points"
    assert [x["side"] for x in result["research_probabilities"]] == ["over", "under"]
    assert abs(sum(x["research_probability"] for x in result["research_probabilities"]) - 1) < 1e-6
    assert result["calibration_independently_validated"] is False
    assert result["betting_enabled"] is False
    assert result["production_approved"] is False
    assert "PRIVATE_ESPN_ID" not in str(result)
    assert "PRIVATE_BOOK" not in str(result)


@pytest.mark.parametrize("change", [
    {"bdl_player_id": 20},
    {"source_player_id": "different"},
    {"canonical_event_id": "different"},
    {"independent_source_reviewed": False},
    {"event_starts_at": (NOW + timedelta(hours=1)).isoformat()},
    {"source_record_sha256": "bad"},
])
def test_crosswalk_mismatch_or_unreviewed_evidence_rejected(change):
    assert run(cw=crosswalk(**change))["status"] == "UNAVAILABLE"


def test_mutated_crosswalk_digest_fails_closed():
    cw = crosswalk()
    cw["source_player_id"] = "tampered"
    assert run(cw=cw)["reason"] == "IDENTITY_OR_PREGAME_PROVENANCE_UNVERIFIED"


@pytest.mark.parametrize("change", [
    {"player_id": "wrong"},
    {"event_id": "wrong"},
    {"features_available_at": (NOW - timedelta(hours=3)).isoformat()},
    {"source_checksum": "bad"},
    {"integrity": {name: False for name in REQUIRED_INTEGRITY}},
    {"market": "player_assists"},
])
def test_frozen_snapshot_missing_or_invalid_rejected(change):
    assert run(fs=snapshot(**change))["status"] == "UNAVAILABLE"


def test_stale_quote_and_integer_push_capable_line_rejected():
    assert run(raw=offer(updated_at=(NOW - timedelta(hours=1)).isoformat()))["status"] == "UNAVAILABLE"
    result = run(raw=offer(line_value="20"))
    assert result["reason"] == "EXACT_LINE_MODEL_INFERENCE_UNAVAILABLE"


def test_mismatched_model_market_rejected():
    assert run(model=artifact(market="player_rebounds"))["status"] == "UNAVAILABLE"


def test_binary_milestone_research_yes_only():
    raw = offer(prop_type="double_double", line_value="0.5",
                market={"type": "milestone", "odds": 150})
    fs = snapshot(market="player_double_double")
    model = artifact(market="player_double_double", family="binary_logistic",
                     parameters={"coef": [0], "intercept": 0})
    result = run(raw=raw, fs=fs, model=model)
    assert result["status"] == "RESEARCH_ONLY"
    assert result["research_probabilities"] == [
        {"side": "yes", "research_probability": 0.5}
    ]


def test_nhl_is_not_silently_promoted():
    with pytest.raises(ValueError):
        research_goat_exact_line("NHL", offer(), crosswalk(), snapshot(),
                                 artifact(), observed_at=NOW)

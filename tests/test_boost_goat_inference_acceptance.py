"""Synthetic acceptance tests: not live GOAT feed or model calibration evidence."""
from datetime import UTC, datetime, timedelta
from math import log

import pytest

from jabazi.boost_goat_inference_acceptance import audit_exact_line_research
from jabazi.boost_identity_manifest import crosswalk_digest
from jabazi.research.player_features import REQUIRED_INTEGRITY

NOW = datetime(2026, 10, 29, 21, tzinfo=UTC)
START = (NOW + timedelta(hours=2)).isoformat()


def offer(**kw):
    raw = {
        "id": 100, "game_id": 77, "player_id": 19,
        "vendor": "PRIVATE_BOOK", "prop_type": "points",
        "line_value": 20.5, "market": {
            "type": "over_under", "over_odds": -110, "under_odds": -110,
        }, "updated_at": (NOW - timedelta(minutes=1)).isoformat(),
    }
    raw.update(kw)
    return {"sport": "basketball_nba", "raw": raw}


def crosswalk(**kw):
    row = {
        "sport": "NBA", "bdl_game_id": 77, "bdl_player_id": 19,
        "source_namespace": "ESPN", "source_player_id": "PRIVATE_ESPN",
        "source_record_sha256": "a" * 64,
        "canonical_event_id": "PRIVATE_EVENT",
        "event_starts_at": START,
        "reviewed_at": (NOW - timedelta(minutes=15)).isoformat(),
        "independent_source_reviewed": True,
    }
    row.update(kw)
    row["record_sha256"] = crosswalk_digest(row)
    return row


def snapshot(**kw):
    row = {
        "sport": "basketball_nba", "event_id": "PRIVATE_EVENT",
        "player_id": "PRIVATE_ESPN", "market": "player_points",
        "starts_at": START,
        "features_available_at": (NOW - timedelta(minutes=10)).isoformat(),
        "snapshot_id": "playerfs-" + "b" * 20,
        "source_checksum": "c" * 64, "provider": "ESPN",
        "feature_schema_version": "fixture",
        "research_only": False, "production_inputs_verified": True,
        "integrity": {name: True for name in REQUIRED_INTEGRITY},
        "features": {"games_prior": 10.0},
    }
    row.update(kw)
    return row


def artifact(**kw):
    row = {
        "sport": "basketball_nba", "market": "player_points",
        "artifact_type": "player_prop_distribution",
        "stage": "VALIDATING", "model_version": "fixture-nba-v1",
        "family": "count_nb", "feature_names": ["games_prior"],
        "scaler": {"mean": [0], "scale": [1]},
        "parameters": {"coef": [0], "intercept": log(20), "dispersion": 0.2},
        "calibration": None, "validation": {"promotion_passed": False},
    }
    row.update(kw)
    return row


def audit(offers=None, crosswalks=None, snapshots=None, artifacts=None):
    return audit_exact_line_research(
        "NBA", [offer()] if offers is None else offers,
        [crosswalk()] if crosswalks is None else crosswalks,
        [snapshot()] if snapshots is None else snapshots,
        [artifact()] if artifacts is None else artifacts,
        observed_at=NOW,
    )


def test_complete_fixture_generates_two_research_sides_but_no_approval():
    report = audit()
    assert report["status"] == "RESEARCH_ONLY"
    assert report["exact_line_research_estimates"] == 1
    assert report["research_probability_sides"] == 2
    assert report["model_versions_observed"] == ["fixture-nba-v1"]
    assert report["prospective_calibration_verified"] is False
    assert report["crosswalk_truth_independently_confirmed_by_runtime"] is False
    assert report["production_approved"] is False
    assert report["betting_enabled"] is False
    for secret in ("PRIVATE_ESPN", "PRIVATE_BOOK", "PRIVATE_EVENT"):
        assert secret not in str(report)


def test_missing_crosswalk_never_generates_probability():
    report = audit(crosswalks=[])
    assert report["status"] == "UNAVAILABLE"
    assert report["rejections"]["MISSING_OR_AMBIGUOUS_CROSSWALK"] == 1


def test_ambiguous_crosswalk_never_picks_first():
    report = audit(crosswalks=[crosswalk(), crosswalk(source_player_id="OTHER")])
    assert report["exact_line_research_estimates"] == 0
    assert report["rejections"]["CONFLICTING_CROSS_GAME_PLAYER_IDENTITY"] == 1


def test_ambiguous_frozen_snapshot_fails_closed():
    report = audit(snapshots=[snapshot(), snapshot()])
    assert report["rejections"]["MISSING_OR_AMBIGUOUS_FROZEN_FEATURES"] == 1


def test_ambiguous_model_artifact_fails_closed():
    report = audit(artifacts=[artifact(), artifact(model_version="another")])
    assert report["rejections"]["MISSING_OR_AMBIGUOUS_FITTED_MODEL"] == 1


def test_duplicate_quote_not_counted_twice():
    report = audit(offers=[offer(), offer()])
    assert report["exact_line_research_estimates"] == 1
    assert report["rejections"]["DUPLICATE_OFFER"] == 1


@pytest.mark.parametrize("bad", [
    offer(game_id=999), offer(player_id=88), offer(prop_type="not_supported"),
    offer(updated_at=(NOW - timedelta(hours=2)).isoformat()),
])
def test_bad_vendor_offer_cannot_be_accepted(bad):
    report = audit(offers=[bad])
    assert report["exact_line_research_estimates"] == 0


def test_wrong_sport_offer_never_enters_nba_pipeline():
    bad = offer()
    bad["sport"] = "americanfootball_nfl"
    report = audit(offers=[bad])
    assert report["rejections"]["OFFER_WRONG_SPORT_OR_SCHEMA"] == 1


def test_unreviewed_crosswalk_rejected_by_underlying_inference():
    report = audit(crosswalks=[crosswalk(independent_source_reviewed=False)])
    assert report["rejections"]["IDENTITY_OR_PREGAME_PROVENANCE_UNVERIFIED"] == 1


def test_unverified_features_rejected_by_underlying_inference():
    report = audit(snapshots=[snapshot(production_inputs_verified=False)])
    assert report["rejections"]["FROZEN_MODEL_FEATURE_INTEGRITY_UNVERIFIED"] == 1


def test_no_fabricated_probability_from_empty_sources():
    report = audit(offers=[], crosswalks=[], snapshots=[], artifacts=[])
    assert report["status"] == "UNAVAILABLE"
    assert report["exact_line_research_estimates"] == 0


def test_unsupported_sport_rejected():
    with pytest.raises(ValueError):
        audit_exact_line_research(
            "NHL", [], [], [], [], observed_at=NOW,
        )


def test_conflicting_bdl_to_espn_identity_across_games_rejects_all_quotes():
    report = audit(
        offers=[offer()],
        crosswalks=[crosswalk(), crosswalk(bdl_game_id=78, source_player_id="OTHER")],
    )
    assert report["exact_line_research_estimates"] == 0
    assert report["rejections"]["CONFLICTING_CROSS_GAME_PLAYER_IDENTITY"] == 1


def test_two_bdl_players_cannot_share_one_source_identity_across_games():
    report = audit(
        offers=[offer()],
        crosswalks=[crosswalk(), crosswalk(bdl_game_id=78, bdl_player_id=20)],
    )
    assert report["exact_line_research_estimates"] == 0
    assert report["rejections"]["CONFLICTING_CROSS_GAME_PLAYER_IDENTITY"] == 1


def test_same_consistent_player_identity_across_games_does_not_create_conflict():
    report = audit(
        offers=[offer()],
        crosswalks=[crosswalk(), crosswalk(bdl_game_id=78)],
    )
    assert report["exact_line_research_estimates"] == 1
    assert "CONFLICTING_CROSS_GAME_PLAYER_IDENTITY" not in report["rejections"]

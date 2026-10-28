"""Regression tests for archived NBA/NHL joint-probability evidence review.

All examples are synthetic unit fixtures, NOT real calibration evidence.
"""
from copy import deepcopy

import pytest

from jabazi.boost_joint_evidence import audit_frozen_joint_evidence

SHA = "a" * 64


def row(*, sport="basketball_nba", split="test", event="g1",
        ticket="t1", probability=0.6, market=0.55, outcome=1):
    prospective = split == "prospective"
    day = "2026-04-02" if prospective else "2026-02-02"
    return {
        "sport": sport,
        "split": split,
        "event_id": event,
        "ticket_id": ticket,
        "model_version": "joint-v1",
        "probability": probability,
        "outcome": outcome,
        "market_probability": market,
        "market_baseline_kind": "independently_quoted_combined_ticket",
        "predicted_at": day + "T12:00:00Z",
        "forecast_frozen_at": day + "T12:01:00Z",
        "starts_at": day + "T20:00:00Z",
        "result_observed_at": day + "T23:00:00Z",
        "features_available_at": day + "T10:00:00Z",
        "market_observed_at": day + "T11:58:00Z",
        "trained_through": "2026-01-01T00:00:00Z",
        "test_start": "2026-02-01T00:00:00Z",
        "prospective_start": "2026-04-01T00:00:00Z",
        "forecast_snapshot_sha256": SHA,
        "result_snapshot_sha256": "b" * 64,
        "market_snapshot_sha256": "c" * 64,
    }


def test_independent_events_not_ticket_count_drive_sample_threshold():
    sample = [
        row(ticket="t1", probability=0.9),
        row(ticket="t2", probability=0.1, outcome=0),
        row(event="g2", ticket="t3", probability=0.4, outcome=0),
    ]
    result = audit_frozen_joint_evidence(sample, minimum_events=3)
    report = result["reports"][0]
    assert report["tickets"] == 3
    assert report["independent_events"] == 2
    assert report["status"] == "INSUFFICIENT_INDEPENDENT_EVENTS"
    assert result["approved_for_betting"] is False
    assert result["all_requested_sports_verified"] is False


def test_both_sports_and_splits_always_research_only():
    sample = []
    for sport in ("basketball_nba", "icehockey_nhl"):
        sample.append(row(sport=sport, event="test_" + sport))
        sample.append(row(sport=sport, split="prospective",
                          event="prospective_" + sport))
    result = audit_frozen_joint_evidence(sample, minimum_events=1)
    assert result["all_requested_sports_verified"] is True
    assert len(result["reports"]) == 4
    assert all(x["status"] == "REQUIRES_PROSPECTIVE_EXPERT_REVIEW"
               and x["approved_for_betting"] is False
               for x in result["reports"])


def test_missing_prospective_partition_reported_not_inferred():
    result = audit_frozen_joint_evidence([row()], minimum_events=1)
    assert result["reports"][1]["split"] == "prospective"
    assert result["reports"][1]["status"] == "MISSING_EVIDENCE"
    assert not result["approved_for_betting"]


@pytest.mark.parametrize("field,value,match", [
    ("forecast_snapshot_sha256", "", "checksum"),
    ("result_snapshot_sha256", "hi", "checksum"),
    ("market_baseline_kind", "independence_product", "baseline"),
    ("probability", 1.2, "probability"),
    ("market_probability", float("nan"), "probability"),
    ("outcome", True, "settlement"),
    ("split", "train", "test and prospective"),
    ("predicted_at", "2026-02-02T21:00:00Z", "point-in-time"),
    ("features_available_at", "2026-02-02T14:00:00Z", "point-in-time"),
    ("forecast_frozen_at", "2026-02-02T22:00:00Z", "point-in-time"),
    ("market_observed_at", "2026-02-02T11:00:00Z", "stale"),
    ("trained_through", "2026-03-01T00:00:00Z", "chronological"),
    ("starts_at", "2026-04-02T20:00:00Z", "Test observation"),
])
def test_invalid_provenance_is_rejected(field, value, match):
    sample = row()
    sample[field] = value
    with pytest.raises(ValueError, match=match):
        audit_frozen_joint_evidence([sample])


def test_test_prospective_event_overlap_is_rejected():
    with pytest.raises(ValueError, match="leaked"):
        audit_frozen_joint_evidence([
            row(),
            row(split="prospective", ticket="other"),
        ])


def test_duplicate_frozen_ticket_rejected():
    first = row()
    with pytest.raises(ValueError, match="Duplicate"):
        audit_frozen_joint_evidence([first, deepcopy(first)])


def test_market_logloss_and_brier_are_separate_metrics():
    good = row(probability=0.8, market=0.4, outcome=1)
    result = audit_frozen_joint_evidence([good], minimum_events=1)
    report = result["reports"][0]
    assert report["model"]["event_weighted_brier"] == pytest.approx(0.04)
    assert report["market_baseline"]["event_weighted_brier"] == pytest.approx(0.36)
    assert report["brier_improvement"] == pytest.approx(0.32)
    assert report["approved_for_betting"] is False


def test_prospective_cutoff_cannot_drift_with_same_model_version():
    sample = row(event="g1")
    different = row(event="g2", ticket="t2")
    different["trained_through"] = "2026-01-02T00:00:00Z"
    with pytest.raises(ValueError, match="inconsistent training"):
        audit_frozen_joint_evidence([sample, different])


def test_empty_input_does_not_approve_or_invent_evidence():
    result = audit_frozen_joint_evidence([])
    assert result["reports"] == []
    assert result["sport_groups"] == 0
    assert result["approved_for_betting"] is False

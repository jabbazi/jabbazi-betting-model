import json
from pathlib import Path

import pytest

from jabazi.research.model_audit import audit_report, calibration_summary


def test_committed_reports_match_artifacts_and_remain_unapproved():
    root = Path(__file__).resolve().parents[1]
    for sport in ("mlb", "nfl"):
        report = json.loads(
            (root / f"docs/experiments/score-distributions/{sport}-report.json").read_text()
        )
        artifact = json.loads(
            (root / f"src/jabazi/models/artifacts/{sport}_scores.json").read_text()
        )
        audit = audit_report(report, artifact)
        assert not audit["approved_for_betting"]
        assert audit["blockers"]
        if sport == "nfl":
            assert audit["paired_market_sample"] == 284
            assert audit["brier_model_minus_market"] > 0
        else:
            assert audit["paired_market_sample"] == 0
            assert audit["brier_model_minus_market"] is None
        with pytest.raises(ValueError):
            audit_report(report, artifact | {"source_checksum": "wrong"})


def test_calibration_weights_buckets_by_observation_count():
    metrics = {
        "n": 10,
        "reliability": [
            {"n": 9, "mean_probability": 0.5, "observed_rate": 0.5},
            {"n": 1, "mean_probability": 0.9, "observed_rate": 0},
        ],
    }
    assert calibration_summary(metrics)["expected_calibration_error"] == pytest.approx(0.09)
    assert calibration_summary(metrics | {"n": 11})["expected_calibration_error"] is None


def test_apparent_good_scores_cannot_self_approve_a_model():
    report = {
        "model_version": "TEST",
        "source_checksum": "TEST",
        "paired_market_diagnostic": {
            "model": {"n": 10, "brier": 0.1},
            "market": {"n": 10, "brier": 0.2},
            "timestamp_verified_prices": 10,
        },
    }
    audit = audit_report(report, report)
    assert not audit["approved_for_betting"] and audit["status"] == "RESEARCH_ONLY"

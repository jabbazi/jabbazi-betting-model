from jabazi.reliability.v42 import ModelStage
from jabazi.reliability.v5 import disagreement_safety_state, evaluate_production_health


def test_quarantined_stage_is_explicit():
    assert ModelStage.QUARANTINED.value == "QUARANTINED"


def test_disagreement_thresholds_are_unambiguous():
    assert disagreement_safety_state(0.55, 0.51)["state"] == "NORMAL"
    assert disagreement_safety_state(0.56, 0.51)["state"] == "LARGE_DISAGREEMENT"
    assert disagreement_safety_state(0.61, 0.51)["state"] == "LARGE_DISAGREEMENT"
    assert disagreement_safety_state(0.611, 0.51)["state"] == "EXTREME_DISAGREEMENT"


def test_integrity_failure_quarantines_immediately():
    result = evaluate_production_health(
        sample_count=500,
        calibration_ece=0.01,
        relative_brier_deterioration=0.0,
        mean_clv_prob_points=1.0,
        negative_clv_confidence=0.0,
        leakage_detected=True,
    )
    assert result["state"] == "QUARANTINED"
    assert result["cash_influence"] is False


def test_ece_over_five_points_demotes_after_sample_floor():
    result = evaluate_production_health(
        sample_count=100,
        calibration_ece=0.051,
        relative_brier_deterioration=0.0,
        mean_clv_prob_points=1.0,
        negative_clv_confidence=0.0,
    )
    assert result["state"] == "LIMITED_LIVE"
    assert "CALIBRATION_ECE_GT_5PP" in result["reasons"]


def test_negative_clv_requires_sample_and_confidence_before_demotion():
    healthy_small_sample = evaluate_production_health(
        sample_count=149,
        calibration_ece=0.02,
        relative_brier_deterioration=0.0,
        mean_clv_prob_points=-0.2,
        negative_clv_confidence=0.99,
    )
    assert healthy_small_sample["state"] == "PRODUCTION_APPROVED"

    demoted = evaluate_production_health(
        sample_count=150,
        calibration_ece=0.02,
        relative_brier_deterioration=0.0,
        mean_clv_prob_points=-0.2,
        negative_clv_confidence=0.90,
    )
    assert demoted["state"] == "LIMITED_LIVE"
    assert "NEGATIVE_CLV_WITH_90PCT_CONFIDENCE" in demoted["reasons"]

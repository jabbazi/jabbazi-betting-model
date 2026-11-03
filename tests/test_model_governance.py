from jabazi.research.governance import (
    canary_policy,
    evidence_card_from_bucket,
    rollback_manifest,
)


def _bucket(n=120):
    return {
        "bucket": "spread",
        "model_version": "v1",
        "stage": "VALIDATING",
        "identity_failures": 0,
        "input_verified": n,
        "first_predicted_at": "2026-09-01T12:00:00+00:00",
        "last_predicted_at": "2026-09-30T12:00:00+00:00",
        "model": {"n": n, "brier": 0.20, "log_loss": 0.60},
        "market": {"n": n, "brier": 0.22, "log_loss": 0.62},
        "calibration": [
            {"n": n, "mean_probability": 0.55, "observed_hit_rate": 0.54}
        ],
    }


def test_evidence_card_is_honest_about_missing_economic_evidence():
    card = evidence_card_from_bucket(_bucket())
    assert card["effective_n"] == 120
    assert card["prospective_days"] == 30
    assert "CLV_ECONOMIC_EVIDENCE" in card["failed_gates"]
    assert card["roi"] is None and card["mean_clv_prob_points"] is None


def test_bad_identity_blocks_data_integrity():
    row = _bucket()
    row["identity_failures"] = 1
    card = evidence_card_from_bucket(row)
    assert "DATA_INTEGRITY" in card["failed_gates"]


def test_canary_caps_high_variance_more_strictly():
    assert canary_policy("LIMITED_LIVE", high_variance=True)["max_fraction"] == 0.10
    assert canary_policy("LIMITED_LIVE", high_variance=False)["max_fraction"] == 0.25
    assert canary_policy("PRODUCTION_APPROVED")["eligible"] is False


def test_rollback_returns_to_limited_live():
    plan = rollback_manifest(
        current_version="v2", previous_approved_version="v1", reason="calibration regression"
    )
    assert plan["to_version"] == "v1"
    assert plan["post_rollback_stage"] == "LIMITED_LIVE"

import pytest

from jabazi.research.advanced_validation import (
    EvidenceCard,
    calibration_bucket_status,
    cluster_bootstrap_ci,
    cluster_effective_sample_size,
    mean_field,
    promotion_gate_matrix,
)


def test_effective_n_penalizes_correlated_alternate_lines():
    rows = [
        {"event_id": "g1", "player": "p1", "line": x}
        for x in (50, 60, 70, 80, 90)
    ] + [{"event_id": "g2", "player": "p2", "line": 50}]
    assert len(rows) == 6
    assert cluster_effective_sample_size(rows) < 3


def test_effective_n_equals_raw_n_for_unique_clusters():
    rows = [{"event_id": f"g{i}"} for i in range(10)]
    assert cluster_effective_sample_size(rows) == pytest.approx(10)


def test_cluster_bootstrap_is_deterministic_and_ordered():
    rows = [
        {"event_id": f"g{i // 2}", "roi": (-1 if i % 3 == 0 else 1)}
        for i in range(20)
    ]
    a = cluster_bootstrap_ci(rows, mean_field("roi"), iterations=200, seed=42)
    b = cluster_bootstrap_ci(rows, mean_field("roi"), iterations=200, seed=42)
    assert a == b
    assert a[0] <= a[1]


def test_calibration_bucket_needs_fifty_effective_observations():
    assert calibration_bucket_status(49.99) == "INSUFFICIENT_SAMPLE"
    assert calibration_bucket_status(50) == "MEANINGFUL"


def test_critical_gate_blocks_promotion():
    result = promotion_gate_matrix(
        {
            "DATA_INTEGRITY": True,
            "LEAKAGE": True,
            "CALIBRATION": False,
            "PREDICTIVE_QUALITY": True,
            "DRIFT": True,
        },
        {"DATA_INTEGRITY", "LEAKAGE", "CALIBRATION", "PREDICTIVE_QUALITY", "DRIFT"},
    )
    assert result["eligible"] is False
    assert result["blocking_gate"] == "CALIBRATION"


def test_evidence_card_explains_stage():
    card = EvidenceCard(
        model="NFL_ANYTIME_TD",
        version="v4.3",
        stage="VALIDATING",
        raw_n=212,
        effective_n=168,
        prospective_days=47,
        passed_gates=("CALIBRATION",),
        failed_gates=("PROSPECTIVE_EFFECTIVE_SAMPLE",),
        blocking_gate="PROSPECTIVE_EFFECTIVE_SAMPLE",
        next_review="effective_n=600",
    )
    assert card.as_dict()["blocking_gate"] == "PROSPECTIVE_EFFECTIVE_SAMPLE"

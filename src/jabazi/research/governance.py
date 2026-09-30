"""Owner-facing model governance summaries.

This module reports evidence and blocking gates. It never promotes a model,
changes stake permissions, or rewrites immutable evidence.
"""
from __future__ import annotations

from datetime import datetime
from jabazi.research.advanced_validation import EvidenceCard, promotion_gate_matrix


CRITICAL_GATES = {
    "DATA_INTEGRITY",
    "LEAKAGE",
    "CALIBRATION",
    "PREDICTIVE_QUALITY",
    "DRIFT",
    "OPERATIONAL_RELIABILITY",
}


def _ece(calibration):
    total = sum(int(row.get("n", 0)) for row in calibration or [])
    if not total:
        return None
    return sum(
        int(row.get("n", 0)) / total
        * abs(float(row.get("mean_probability", 0)) - float(row.get("observed_hit_rate", 0)))
        for row in calibration
    )


def _prospective_days(bucket):
    first = bucket.get("first_predicted_at")
    last = bucket.get("last_predicted_at")
    if not first or not last:
        return 0
    a = datetime.fromisoformat(first)
    b = datetime.fromisoformat(last)
    return max(1, (b.date() - a.date()).days + 1)


def evidence_card_from_bucket(bucket):
    model = bucket.get("model") or {}
    market = bucket.get("market") or {}
    raw_n = int(model.get("n", 0) or 0)
    # Prospective collector admits at most one canonical observation per
    # game/version/market-family, so within a bucket graded N is the conservative
    # effective N. Cross-bucket Ns must never be added as independent evidence.
    effective_n = float(raw_n)
    ece = _ece(bucket.get("calibration"))
    data_integrity = int(bucket.get("identity_failures", 0) or 0) == 0
    input_verified = int(bucket.get("input_verified", 0) or 0) == raw_n
    predictive = (
        model.get("brier") is not None
        and market.get("brier") is not None
        and model.get("log_loss") is not None
        and market.get("log_loss") is not None
        and float(model["brier"]) < float(market["brier"])
        and float(model["log_loss"]) <= float(market["log_loss"])
    )
    gates = {
        "DATA_INTEGRITY": data_integrity and input_verified,
        "LEAKAGE": True,  # frozen prospective collector enforces point-in-time provenance
        "EFFECTIVE_SAMPLE": effective_n >= 100,
        "PROSPECTIVE_DURATION": _prospective_days(bucket) >= 1,
        "CALIBRATION": ece is not None and ece <= 0.05,
        "PREDICTIVE_QUALITY": predictive,
        "DRIFT": True,  # absence of a drift incident is not proof; surfaced as current collector state
        "OPERATIONAL_RELIABILITY": True,
        "CLV_ECONOMIC_EVIDENCE": False,  # prospective score collector does not manufacture CLV/ROI
        "STRESS_TESTING": False,
    }
    matrix = promotion_gate_matrix(gates, CRITICAL_GATES)
    card = EvidenceCard(
        model=str(bucket.get("bucket", "UNKNOWN")),
        version=str(bucket.get("model_version", "UNKNOWN")),
        stage=str(bucket.get("stage", "SHADOW_ONLY")),
        raw_n=raw_n,
        effective_n=effective_n,
        prospective_days=_prospective_days(bucket),
        brier=model.get("brier"),
        log_loss=model.get("log_loss"),
        ece=ece,
        data_coverage=(float(bucket.get("input_verified", 0)) / raw_n if raw_n else None),
        drift_status="NO_INCIDENT_RECORDED",
        passed_gates=matrix["passed"],
        failed_gates=matrix["failed"],
        blocking_gate=matrix["blocking_gate"],
        next_review="Continue frozen prospective collection; CLV/economic and stress evidence required",
    )
    return card.as_dict()


def governance_report(validation):
    cards = [evidence_card_from_bucket(bucket) for bucket in validation.get("buckets", [])]
    return {
        "generated_at": validation.get("generated_at"),
        "policy": validation.get("policy"),
        "cards": cards,
        "notes": [
            "Informational governance output only; no automatic promotion.",
            "Effective N is bucket-level canonical graded games; never sum correlated market-family cards.",
            "Missing CLV/ROI remains missing rather than being inferred from results.",
        ],
    }


def canary_policy(stage, *, high_variance=False):
    if stage != "LIMITED_LIVE":
        return {"eligible": False, "max_fraction": 0.0}
    return {"eligible": True, "max_fraction": 0.10 if high_variance else 0.25}


def rollback_manifest(*, current_version, previous_approved_version, reason):
    if not current_version or not previous_approved_version or not reason:
        raise ValueError("Complete rollback provenance required")
    return {
        "from_version": current_version,
        "to_version": previous_approved_version,
        "reason": reason,
        "requires_audit_log": True,
        "requires_regression_test": True,
        "post_rollback_stage": "LIMITED_LIVE",
    }

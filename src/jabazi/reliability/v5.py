"""V5 calibration segmentation and advanced reliability gates."""
from __future__ import annotations

from jabazi.research.prospective import calibration_table


NORMAL_DISAGREEMENT_PP = 5.0
EXTREME_DISAGREEMENT_PP = 10.0


def segment_key(row):
    p = float(row["probability"])
    market = float(row["market_probability"])
    gap = abs(p - market)
    return (
        row["sport"],
        row["bucket"],
        "favorite" if market >= 0.5 else "underdog",
        "edge_0_2" if gap < 0.02 else "edge_2_5" if gap < 0.05 else "edge_5_plus",
    )


def segmented_calibration(rows):
    groups = {}
    for row in rows:
        y = row.get("outcome")
        if y not in (0, 1):
            continue
        groups.setdefault(segment_key(row), []).append(
            (float(row["probability"]), int(y))
        )
    output = []
    for key, pairs in sorted(groups.items()):
        table = calibration_table(pairs)
        ece = (
            sum(
                bucket["n"] / len(pairs)
                * abs(bucket["mean_probability"] - bucket["observed_hit_rate"])
                for bucket in table
            )
            if pairs
            else None
        )
        output.append(
            {
                "sport": key[0],
                "bucket": key[1],
                "market_side": key[2],
                "edge_band": key[3],
                "n": len(pairs),
                "ece": ece,
                "calibration": table,
            }
        )
    return output


def disagreement_safety_state(model_probability, market_probability):
    """Classify model-market disagreement in percentage points.

    NORMAL: <5 pp
    LARGE_DISAGREEMENT: 5-10 pp inclusive
    EXTREME_DISAGREEMENT: >10 pp
    """
    if model_probability is None or market_probability is None:
        return {"state": "UNAVAILABLE", "gap_pp": None}
    gap_pp = 100.0 * abs(float(model_probability) - float(market_probability))
    if gap_pp > EXTREME_DISAGREEMENT_PP:
        state = "EXTREME_DISAGREEMENT"
    elif gap_pp >= NORMAL_DISAGREEMENT_PP:
        state = "LARGE_DISAGREEMENT"
    else:
        state = "NORMAL"
    return {"state": state, "gap_pp": gap_pp}


def evaluate_production_health(
    *,
    sample_count=0,
    calibration_ece=None,
    relative_brier_deterioration=None,
    mean_clv_prob_points=None,
    negative_clv_confidence=None,
    feature_coverage=1.0,
    stale_invalid_rate=0.0,
    drift=False,
    identity_failures=0,
    mapping_failures=0,
    leakage_detected=False,
    version_mismatch=False,
):
    """Evaluate automatic production demotion/quarantine rules.

    Severe integrity failures quarantine immediately. Statistical deterioration
    demotes to LIMITED_LIVE only after the configured evidence floor is met.
    """
    reasons = []

    if leakage_detected:
        reasons.append("DATA_LEAKAGE")
    if identity_failures:
        reasons.append("IDENTITY_FAILURE")
    if mapping_failures:
        reasons.append("MARKET_MAPPING_FAILURE")
    if version_mismatch:
        reasons.append("MODEL_VERSION_MISMATCH")

    if reasons:
        return {
            "state": "QUARANTINED",
            "reasons": reasons,
            "cash_influence": False,
        }

    if sample_count >= 100 and calibration_ece is not None and calibration_ece > 0.05:
        reasons.append("CALIBRATION_ECE_GT_5PP")
    if (
        sample_count >= 100
        and relative_brier_deterioration is not None
        and relative_brier_deterioration > 0.05
    ):
        reasons.append("BRIER_DETERIORATION_GT_5PCT")
    if (
        sample_count >= 150
        and mean_clv_prob_points is not None
        and mean_clv_prob_points < 0
        and negative_clv_confidence is not None
        and negative_clv_confidence >= 0.90
    ):
        reasons.append("NEGATIVE_CLV_WITH_90PCT_CONFIDENCE")
    if feature_coverage < 0.97:
        reasons.append("FEATURE_COVERAGE_LT_97PCT")
    if stale_invalid_rate > 0.01:
        reasons.append("STALE_INVALID_RATE_GT_1PCT")
    if drift:
        reasons.append("FEATURE_OR_PREDICTION_DRIFT")

    state = "LIMITED_LIVE" if reasons else "PRODUCTION_APPROVED"
    return {
        "state": state,
        "reasons": reasons,
        "cash_influence": state == "PRODUCTION_APPROVED",
    }


def kill_switch(
    *,
    data_health,
    drift,
    calibration_ece,
    recent_brier_delta,
    identity_failures,
    provider_failures=0,
    sample_count=0,
):
    """Return the strongest fail-closed state supported by current evidence."""
    reasons = []
    if identity_failures:
        reasons.append("IDENTITY_FAILURE")
    if not data_health:
        reasons.append("DATA_UNHEALTHY")
    if drift:
        reasons.append("FEATURE_DRIFT")
    if provider_failures >= 3:
        reasons.append("REPEATED_PROVIDER_FAILURE")
    if calibration_ece is not None and sample_count >= 100 and calibration_ece > 0.05:
        reasons.append("CALIBRATION_DETERIORATION")
    if recent_brier_delta is not None and sample_count >= 100 and recent_brier_delta > 0.02:
        reasons.append("MARKET_RELATIVE_BRIER_DETERIORATION")
    if identity_failures or not data_health:
        state = "QUARANTINED"
    elif reasons:
        state = "WATCH"
    else:
        state = "NORMAL"
    return {"state": state, "reasons": reasons, "cash_influence": state == "NORMAL"}

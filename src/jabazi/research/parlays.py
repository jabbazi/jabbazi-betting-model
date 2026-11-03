"""Audit research parlays using aligned outcomes from a documented joint model."""

from datetime import datetime
from decimal import Decimal as D
from math import sqrt
from jabazi.domain.pricing import probability, decimal_price, scenario_joint, roi, minimum_decimal


def evaluate_parlay(
    *,
    leg_ids,
    outcomes,
    weights,
    offered_decimal,
    quoted_at,
    now,
    model_version,
    provenance,
    uncertainty=0,
    required_roi=".05",
    max_age_seconds=120,
):
    if not model_version or not provenance:
        raise ValueError("Joint model provenance required")
    if not 2 <= len(leg_ids) <= 4 or len(set(leg_ids)) != len(leg_ids):
        raise ValueError("Require 2–4 distinct legs")
    if not outcomes or any(len(row) != len(leg_ids) for row in outcomes):
        raise ValueError("Aligned joint model scenarios required")
    if not isinstance(quoted_at, datetime) or quoted_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Verified payout timestamp required")
    if not 0 < max_age_seconds <= 120:
        raise ValueError("Invalid price age limit")
    price = decimal_price(offered_decimal)
    joint = scenario_joint(outcomes, weights)
    weights = list(map(probability, weights))
    marginals = [
        sum((w for row, w in zip(outcomes, weights) if row[i]), D(0)) for i in range(len(leg_ids))
    ]
    correlations = []
    for i in range(len(leg_ids)):
        for j in range(i + 1, len(leg_ids)):
            both = sum((w for row, w in zip(outcomes, weights) if row[i] and row[j]), D(0))
            denominator = marginals[i] * (1 - marginals[i]) * marginals[j] * (1 - marginals[j])
            phi = (
                float(both - marginals[i] * marginals[j]) / sqrt(float(denominator))
                if denominator
                else None
            )
            correlations.append({"legs": [leg_ids[i], leg_ids[j]], "phi": phi})
    adjusted = max(D(0), joint - probability(uncertainty))
    expected = roi(adjusted, price)
    age = (now - quoted_at).total_seconds()
    reasons = []
    if not 0 <= age <= max_age_seconds:
        reasons.append("STALE_OR_FUTURE_PAYOUT")
    if expected < D(str(required_roi)):
        reasons.append("INSUFFICIENT_RISK_ADJUSTED_ROI")
    if len(leg_ids) == 4:
        reasons.append("FOUR_LEG_STRUCTURE_REQUIRES_SEPARATE_REVIEW")
    return {
        "status": "PASS" if reasons else "RESEARCH_ONLY",
        "reasons": reasons,
        "legs": leg_ids,
        "marginal_probabilities": marginals,
        "joint_probability": joint,
        "adjusted_joint_probability": adjusted,
        "pairwise_correlations": correlations,
        "fair_decimal": 1 / joint if joint else None,
        "offered_decimal": price,
        "expected_roi": expected,
        "minimum_playable_decimal": minimum_decimal(adjusted, required_roi) if adjusted else None,
        "model_version": model_version,
        "provenance": provenance,
        "approved_for_betting": False,
    }

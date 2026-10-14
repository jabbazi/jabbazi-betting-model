"""Explicit experimental market shrinkage, separate from a pure-model probability."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class BlendEvidence:
    sport: str
    market_bucket: str
    model_version: str
    probability_lower: float
    probability_upper: float
    prospective_samples: int
    model_brier: float | None
    market_brier: float | None
    validated_weight: float | None
    calibration_version: str | None


def blend(raw, market, *, sport, market_bucket, model_version, data_healthy, evidence=None):
    if any(not isfinite(p) or not 0 <= p <= 1 for p in (raw, market)):
        raise ValueError("Invalid probabilities")
    weight = 0.0
    reason = "UNPROVEN_MODEL: market reference only"
    if evidence is not None:
        if (
            evidence.sport != sport
            or evidence.market_bucket != market_bucket
            or evidence.model_version != model_version
            or not evidence.probability_lower <= raw < evidence.probability_upper
        ):
            raise ValueError("Blend evidence identity mismatch")
        w = evidence.validated_weight
        if w is not None and (not isfinite(w) or not 0 <= w <= 1):
            raise ValueError("Invalid validated weight")
        if (
            data_healthy
            and evidence.prospective_samples > 0
            and evidence.calibration_version
            and evidence.model_brier is not None
            and evidence.market_brier is not None
            and evidence.model_brier < evidence.market_brier
            and w is not None
        ):
            weight = w
            reason = "Frozen bucket-specific weight supplied"
    return {
        "pure_model_probability": raw,
        "market_no_vig_probability": market,
        "market_aware_probability": weight * raw + (1 - weight) * market,
        "model_weight": weight,
        "reason": reason,
        "approved_for_betting": False,
    }

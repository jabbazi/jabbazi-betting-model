"""Match archived prop quotes to validated player-model estimates.

This adapter does not promote SHADOW_ONLY models or infer probabilities
from sportsbook prices.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelMatch:
    status: str
    probability: object | None
    model_version: str | None
    reason: str | None


def match_player_model(price, player_models) -> ModelMatch:
    key = (price.sport, price.market)
    model = player_models.get(key)
    if model is None and price.market.endswith("_alternate"):
        model = player_models.get((price.sport, price.market.removesuffix("_alternate")))
    if model is None:
        return ModelMatch("UNAVAILABLE", None, None, "NO_MATCHING_PLAYER_MODEL")
    if getattr(model, "stage", None) != "PRODUCTION_APPROVED":
        return ModelMatch("RESEARCH_ONLY", None, getattr(model, "model_version", None),
                          "MODEL_NOT_PRODUCTION_APPROVED")
    artifact = getattr(model, "artifact", {})
    validation = artifact.get("validation", {}) if isinstance(artifact, dict) else {}
    version = getattr(model, "model_version", None)
    if not isinstance(validation, dict) or validation.get("promotion_passed") is not True:
        return ModelMatch("RESEARCH_ONLY", None, version, "MODEL_PROMOTION_EVIDENCE_MISSING")
    if not isinstance(version, str) or not version.strip():
        return ModelMatch("UNAVAILABLE", None, None, "MODEL_VERSION_MISSING")
    try:
        estimate = model.estimate(price)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return ModelMatch("UNAVAILABLE", None, None, "MODEL_ESTIMATE_FAILED")
    if estimate is None:
        return ModelMatch("UNAVAILABLE", None, None, "MODEL_INPUTS_UNAVAILABLE")
    if getattr(estimate, "model_version", None) != version:
        return ModelMatch("UNAVAILABLE", None, None, "MODEL_VERSION_MISMATCH")
    snapshot = getattr(estimate, "feature_snapshot", {})
    integrity = snapshot.get("integrity", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(integrity, dict):
        return ModelMatch("UNAVAILABLE", None, None, "PLAYER_INTEGRITY_UNVERIFIED")
    required = ("event_identity", "player_identity", "role",
                "availability", "fresh_features")
    if not all(integrity.get(field) is True for field in required):
        return ModelMatch("UNAVAILABLE", None, None, "PLAYER_INTEGRITY_UNVERIFIED")
    p = getattr(estimate, "probability", None)
    from jabazi.domain.pricing import probability
    try:
        p = probability(p)
    except (ValueError, TypeError):
        return ModelMatch("UNAVAILABLE", None, None, "INVALID_MODEL_PROBABILITY")
    return ModelMatch("MODEL_ESTIMATE", p, getattr(estimate, "model_version", None), None)

"""Read-only readiness assessment for NBA/NHL boost joint-player research.

Existing marginal player artifacts are not proof of validated joint probabilities.
"""
from __future__ import annotations


def boost_model_readiness(player_models, joint_models=None):
    """Summarize approved marginal markets and joint-model evidence by sport."""
    joint_models = joint_models or {}
    results = {}
    for sport in ("basketball_nba", "icehockey_nhl"):
        relevant = {
            market: model for (model_sport, market), model in player_models.items()
            if model_sport == sport
        }
        markets = {}
        for market, model in sorted(relevant.items()):
            validation = getattr(model, "artifact", {}).get("validation", {})
            approved = (getattr(model, "stage", None) == "PRODUCTION_APPROVED"
                        and validation.get("promotion_passed") is True)
            markets[market] = {
                "stage": getattr(model, "stage", "UNAVAILABLE"),
                "approved": approved,
                "version": getattr(model, "model_version", None),
                "reason": validation.get("reason"),
            }
        joint = joint_models.get(sport)
        joint_approved = bool(
            joint is not None
            and getattr(joint, "approved_for_betting", False) is True
            and getattr(joint, "prospective_calibration_passed", False) is True
        )
        results[sport] = {
            "marginal_markets": markets,
            "joint_model_approved": joint_approved,
            "automated_boost_recommendation_enabled": joint_approved
                and bool(markets) and all(x["approved"] for x in markets.values()),
            "reason": None if joint_approved else "JOINT_PROSPECTIVE_CALIBRATION_NOT_VERIFIED",
        }
    return results

"""Read-only readiness assessment for NBA/NHL boost joint-player research.

Existing marginal player artifacts are not proof of validated joint probabilities.
"""
from __future__ import annotations

import math


def _finite_probability(value):
    return (type(value) in (int, float)
            and math.isfinite(value) and 0 <= value <= 1)


MIN_INDEPENDENT_GAMES_PER_SPLIT = 200


def _sufficient_independent_games(value):
    return type(value) is int and value >= MIN_INDEPENDENT_GAMES_PER_SPLIT


def _positive_samples(value):
    return type(value) is int and value > 0


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
                        and validation.get("promotion_passed") is True
                        and _positive_samples(validation.get("prospective_sample_count"))
                        and _finite_probability(validation.get("ece"))
                        and _finite_probability(validation.get("market_baseline_brier"))
                        and _finite_probability(validation.get("brier"))
                        and validation["brier"] < validation["market_baseline_brier"]
                        and _sufficient_independent_games(validation.get("test_independent_games"))
                        and _sufficient_independent_games(validation.get("prospective_independent_games"))
                        and validation.get("source_evidence_reviewed") is True)
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
            and getattr(joint, "independent_benchmark_passed", False) is True
            and _positive_samples(getattr(joint, "prospective_sample_count", None))
            and _finite_probability(getattr(joint, "calibration_ece", None))
            and _sufficient_independent_games(getattr(joint, "test_independent_games", None))
            and _sufficient_independent_games(getattr(joint, "prospective_independent_games", None))
            and getattr(joint, "source_evidence_reviewed", False) is True
        )
        results[sport] = {
            "marginal_markets": markets,
            "joint_model_approved": joint_approved,
            "joint_prospective_samples": getattr(joint, "prospective_sample_count", 0) if joint else 0,
            "joint_independent_benchmark_passed": (
                getattr(joint, "independent_benchmark_passed", False) is True if joint else False
            ),
            "automated_boost_recommendation_enabled": joint_approved
                and bool(markets) and all(x["approved"] for x in markets.values()),
            "reason": None if joint_approved else "JOINT_PROSPECTIVE_CALIBRATION_NOT_VERIFIED",
        }
    return results

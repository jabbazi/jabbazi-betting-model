"""Independent player-prop model registry.

A malformed player artifact fails closed for that market only.  Team models continue
independently so missing prop evidence cannot break the broader scanner.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .player_distribution import PLAYER_PROP_MARKETS, PlayerPropModel

DEFAULT_DIR = Path("models/player_props")


def _entity(sport: str, market: str) -> str:
    return f"{sport}|{market}"


def load_player_models(store=None):
    result, errors = {}, []
    base = Path(os.getenv("JABBAZI_PLAYER_MODEL_DIR", str(DEFAULT_DIR)))
    for sport, markets in PLAYER_PROP_MARKETS.items():
        for market in sorted(markets):
            records = (
                store.list_records("player_prop_model", 1, entity=_entity(sport, market))
                if store is not None
                else []
            )
            path = base / sport / f"{market}.json"
            if not records and not path.exists():
                continue
            try:
                artifact = records[0]["payload"] if records else json.loads(path.read_text())
                if artifact.get("status") == "UNAVAILABLE":
                    continue
                model = PlayerPropModel(artifact, store)
                if model.sport != sport or model.market != market:
                    raise ValueError("Player artifact identity mismatch")
                result[(sport, market)] = model
            except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                errors.append(f"{sport}:{market}:player_model_load_{type(exc).__name__}")
    return result, errors


def player_status(player_models, sport: str):
    models = [
        model for (model_sport, _), model in player_models.items()
        if model_sport == sport
    ]
    if not models:
        return {
            "status": "UNAVAILABLE",
            "approved_for_betting": False,
            "supported_markets": [],
            "market_buckets": {},
        }
    stages = {model.stage for model in models}
    overall = (
        "PRODUCTION_APPROVED"
        if stages == {"PRODUCTION_APPROVED"}
        else "LIMITED_LIVE"
        if "PRODUCTION_APPROVED" in stages or "LIMITED_LIVE" in stages
        else "VALIDATING"
        if "VALIDATING" in stages
        else "SHADOW_ONLY"
    )
    buckets = {}
    for model in models:
        validation = model.artifact.get("validation", {})
        buckets[model.market] = {
            "stage": model.stage,
            "model_version": model.artifact["model_version"],
            "approved_for_betting": (
                model.stage == "PRODUCTION_APPROVED"
                and validation.get("promotion_passed") is True
            ),
            "test_sample_count": validation.get("test_sample_count", 0),
            "prospective_sample_count": validation.get("prospective_sample_count", 0),
            "brier": validation.get("brier"),
            "market_baseline_brier": validation.get("market_baseline_brier"),
            "ece": validation.get("ece"),
            "mean_clv_prob_points": validation.get("prospective_mean_clv_prob_points"),
            "reason": validation.get("reason", "Validation evidence unavailable"),
        }
    return {
        "status": overall,
        "approved_for_betting": all(
            bucket["approved_for_betting"] for bucket in buckets.values()
        ),
        "supported_markets": sorted(buckets),
        "market_buckets": buckets,
    }

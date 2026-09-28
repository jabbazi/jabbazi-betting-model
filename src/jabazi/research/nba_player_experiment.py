"""Provider-neutral causal NBA player-prop dataset construction.

Input rows must come from a separately verified historical provider/export. This module
does not fetch or infer missing NBA data. Every feature uses only earlier completed
games whose result_available_at precedes the historical prediction timestamp.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import hashlib
import json
import math
from statistics import pstdev

from jabazi.models.team_elo import timestamp

SPORT = "basketball_nba"
MARKETS = frozenset({
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_blocks",
    "player_steals",
    "player_turnovers",
    "player_points_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
    "player_double_double",
})
COMPONENTS = {
    "player_points": ("points",),
    "player_rebounds": ("rebounds",),
    "player_assists": ("assists",),
    "player_threes": ("threes",),
    "player_blocks": ("blocks",),
    "player_steals": ("steals",),
    "player_turnovers": ("turnovers",),
    "player_points_rebounds_assists": ("points", "rebounds", "assists"),
    "player_points_rebounds": ("points", "rebounds"),
    "player_points_assists": ("points", "assists"),
    "player_rebounds_assists": ("rebounds", "assists"),
}
BOX = ("points", "rebounds", "assists", "threes", "blocks", "steals", "turnovers")


def _finite(value, label):
    if isinstance(value, bool):
        raise ValueError(f"Invalid NBA {label}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite NBA {label}")
    return value


def _mean(values, n):
    values = list(values)[-n:]
    return sum(values) / len(values) if values else 0.0


def _target(row, market):
    if market == "player_double_double":
        categories = sum(float(row[name]) >= 10 for name in ("points", "rebounds", "assists", "blocks", "steals"))
        return int(categories >= 2)
    return int(sum(float(row[name]) for name in COMPONENTS[market]))


def _features(history, current):
    minutes = [float(row["minutes"]) for row in history]
    output = {
        "last1_minutes": minutes[-1],
        "mean3_minutes": _mean(minutes, 3),
        "mean5_minutes": _mean(minutes, 5),
        "mean10_minutes": _mean(minutes, 10),
        "std5_minutes": pstdev(minutes[-5:]) if len(minutes[-5:]) >= 2 else 0.0,
        "games_prior": float(len(history)),
        "is_home": float(bool(current["is_home"])),
    }
    for stat in BOX:
        values = [float(row[stat]) for row in history]
        output[f"mean3_{stat}"] = _mean(values, 3)
        output[f"mean5_{stat}"] = _mean(values, 5)
        output[f"mean10_{stat}"] = _mean(values, 10)
        output[f"per_minute5_{stat}"] = (
            sum(values[-5:]) / max(sum(minutes[-5:]), 1.0)
        )
    return output


def normalize_rows(rows):
    result, seen = [], set()
    required = {
        "event_id", "player_id", "participant", "starts_at", "result_available_at",
        "minutes", "is_home", *BOX,
    }
    for raw in rows:
        if not required <= set(raw):
            raise ValueError("NBA historical row missing required fields")
        key = (str(raw["event_id"]), str(raw["player_id"]))
        if not all(key) or key in seen:
            raise ValueError("Duplicate or missing NBA event/player identity")
        seen.add(key)
        start, available = timestamp(raw["starts_at"]), timestamp(raw["result_available_at"])
        if available <= start:
            raise ValueError("NBA result availability must follow game start")
        minutes = _finite(raw["minutes"], "minutes")
        if not 0 <= minutes <= 70:
            raise ValueError("NBA minutes outside supported range")
        clean = {
            "event_id": key[0],
            "player_id": key[1],
            "participant": str(raw["participant"]).strip(),
            "starts_at": start,
            "result_available_at": available,
            "minutes": minutes,
            "is_home": bool(raw["is_home"]),
        }
        if not clean["participant"]:
            raise ValueError("NBA participant missing")
        for stat in BOX:
            value = _finite(raw[stat], stat)
            if value < 0 or int(value) != value:
                raise ValueError("NBA box-score counts must be nonnegative integers")
            clean[stat] = int(value)
        if 3 * clean["threes"] > clean["points"]:
            raise ValueError("NBA threes/points coherence failure")
        result.append(clean)
    return sorted(result, key=lambda row: (row["starts_at"], row["event_id"], row["player_id"]))


def build_dataset(
    *,
    rows,
    market,
    provider,
    source_checksum,
    research_rights_reference,
    prediction_lead_hours=6,
):
    if market not in MARKETS:
        raise ValueError("Unsupported NBA player market")
    if not all((provider, source_checksum, research_rights_reference)):
        raise ValueError("NBA dataset provenance is required")
    if not isinstance(prediction_lead_hours, int) or not 1 <= prediction_lead_hours <= 24:
        raise ValueError("Invalid NBA prediction lead")
    rows = normalize_rows(rows)
    prior = defaultdict(list)
    output = []
    for current in rows:
        prediction_at = current["starts_at"] - timedelta(hours=prediction_lead_hours)
        history = [
            row for row in prior[current["player_id"]]
            if row["result_available_at"] < prediction_at and row["minutes"] > 0
        ]
        if len(history) >= 5 and _mean([row["minutes"] for row in history], 5) >= 8:
            features = _features(history[-40:], current)
            output.append({
                "event_id": current["event_id"],
                "player_id": current["player_id"],
                "participant": current["participant"],
                "prediction_at": prediction_at.isoformat(),
                "features_available_at": max(row["result_available_at"] for row in history).isoformat(),
                "starts_at": current["starts_at"].isoformat(),
                "result_available_at": current["result_available_at"].isoformat(),
                "result_status": "final" if current["minutes"] > 0 else "dnp",
                "observed_value": _target(current, market),
                "expected_opportunities": _mean([row["minutes"] for row in history], 5),
                "features": features,
                "market_line": None,
                "market_side": None,
                "market_no_vig_probability": None,
                "closing_no_vig_probability": None,
                "integrity": {
                    "event_identity": True,
                    "player_identity": True,
                    "historical_result_lagged": True,
                    "minutes_observed": True,
                    "same_day_rotation_verified": False,
                    "injury_status_verified": False,
                },
            })
        prior[current["player_id"]].append(current)
    canonical = json.dumps(
        [[r["event_id"], r["player_id"], r["prediction_at"], r["observed_value"], r["features"]]
         for r in output],
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "manifest": {
            "sport": SPORT,
            "market": market,
            "data_mode": "real",
            "provider": provider,
            "source_checksum": source_checksum,
            "dataset_checksum": hashlib.sha256(canonical.encode()).hexdigest(),
            "research_rights_reference": research_rights_reference,
            "feature_schema_version": "nba-player-minutes-box-v1",
            "prediction_lead_hours": prediction_lead_hours,
            "market_prices_included": False,
            "limitations": [
                "No historical sportsbook prop-price archive is included.",
                "Same-day injuries, scratches, starting lineup and rotation changes are not reconstructed.",
                "DNP/void settlement requires separate book-specific handling.",
            ],
        },
        "rows": output,
    }

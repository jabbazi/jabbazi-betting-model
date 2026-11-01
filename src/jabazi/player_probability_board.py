"""Research-only model probability summaries for existing scanner snapshots.

No provider calls, no sportsbook odds interpreted as model hit probabilities,
no synthetic values, and no wagering authorization. A scan can cover only the
event-market subset requested by its existing provider budget.
"""
from __future__ import annotations

import math

SPORTS = {
    "basketball_nba": "NBA",
    "americanfootball_nfl": "NFL",
    "icehockey_nhl": "NHL",
}
ALLOWED_STAGES = frozenset({
    "SHADOW_ONLY", "VALIDATING", "LIMITED_LIVE", "PRODUCTION_APPROVED",
})


def _probability(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and 0 < result < 1 else None


def _player_market(row):
    return (
        isinstance(row, dict)
        and row.get("sport") in SPORTS
        and str(row.get("market") or "").startswith("player_")
        and bool(str(row.get("participant") or row.get("player") or "").strip())
    )


def _blank():
    return {
        sport: {
            "status": "NO_PLAYER_MARKET_ROWS",
            "observed_player_market_rows": 0,
            "model_estimate_rows": 0,
            "returned": 0,
            "top10": [],
        }
        for sport in SPORTS.values()
    }


def _finish(sports):
    for bucket in sports.values():
        bucket["top10"].sort(
            key=lambda item: (-item["model_probability"],
                              str(item.get("event_id") or ""),
                              str(item.get("player") or ""),
                              str(item.get("market") or ""))
        )
        seen, unique = set(), []
        for item in bucket["top10"]:
            # Different books and alternate lines should not take all ten spots.
            key = (str(item.get("event_id")), str(item.get("player")).lower(),
                   str(item.get("market")))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
            if len(unique) == 10:
                break
        bucket["top10"] = unique
        bucket["returned"] = len(unique)
        bucket["status"] = (
            "RESEARCH_ESTIMATES_AVAILABLE" if unique
            else "NO_VALID_MODEL_PROBABILITIES" if bucket["observed_player_market_rows"]
            else "NO_PLAYER_MARKET_ROWS"
        )
    return {
        "mode": "RESEARCH_ONLY",
        "probability_basis": "VERSIONED_JABBAZI_MODEL_EXACT_LINE",
        "paid_requests_made": 0,
        "betting_enabled": False,
        "sports": sports,
        "notice": (
            "Only genuine versioned JABBAZI player-model estimates already in "
            "the saved scanner snapshot are shown. No market-implied or LAB "
            "confidence number is relabeled as a model hit probability. "
            "Coverage is bounded by the ordinary scan's markets and credits; "
            "model calibration, complete paid coverage and betting approval "
            "are NOT implied. A blank list is not a forecast of zero."
        ),
    }


def from_scan_actions(rows, *, present):
    """Aggregate one scan's eligible actions, independent of response page.

    `present` is the existing scanner's stale/expiry-safe serializer; it must
    run for every row before its model probability can enter a Top 10 list.
    """
    buckets = _blank()
    for raw in rows:
        if not _player_market(raw):
            continue
        bucket = buckets[SPORTS[raw["sport"]]]
        bucket["observed_player_market_rows"] += 1
        row = present(raw)
        p = _probability(row.get("model_probability"))
        if not (row.get("price_is_current") is True
                and str(row.get("model_version") or "").strip()
                and row.get("probability_status") in ALLOWED_STAGES
                and p is not None):
            continue
        bucket["model_estimate_rows"] += 1
        bucket["top10"].append({
            "sport": SPORTS[raw["sport"]],
            "event_id": row.get("event_id"),
            "event": row.get("event"),
            "player": row.get("participant"),
            "market": row.get("market"),
            "selection": row.get("selection"),
            "line": row.get("line"),
            "model_probability": p,
            "model_stage": row.get("probability_status"),
            "model_version": row.get("model_version"),
            "price_observed_at": row.get("source_timestamp"),
            "starts_at": row.get("starts_at"),
            "approval": "RESEARCH_ONLY",
            "approved_for_betting": False,
        })
    return _finish(buckets)


def from_vip_board(rows, *, sport):
    """Show model-only current probabilities within an authenticated VIP slate."""
    if sport not in SPORTS.values():
        raise ValueError("Unsupported sport")
    buckets = _blank()
    bucket = buckets[sport]
    for row in rows:
        if not _player_market({
            **row, "sport": next((key for key, value in SPORTS.items() if value == row.get("sport")), ""),
            "participant": row.get("player"),
        }) or row.get("sport") != sport:
            continue
        bucket["observed_player_market_rows"] += 1
        p = _probability(row.get("model_probability"))
        if not (
            row.get("fresh") is True
            and row.get("data_health") == "HEALTHY"
            and row.get("status") not in {"QUARANTINED", "INVALIDATED", "SAFETY REVIEW"}
            and str(row.get("model_version") or "").strip()
            and row.get("model_stage") in ALLOWED_STAGES
            and p is not None
        ):
            continue
        bucket["model_estimate_rows"] += 1
        bucket["top10"].append({
            "sport": sport,
            "event_id": row.get("event_id"),
            "event": row.get("event"),
            "player": row.get("player"),
            "market": row.get("market"),
            "selection": row.get("selection"),
            "line": row.get("line"),
            "model_probability": p,
            "model_stage": row.get("model_stage"),
            "model_version": row.get("model_version"),
            "price_observed_at": row.get("price_at"),
            "starts_at": row.get("starts_at"),
            "approval": "RESEARCH_ONLY",
            "approved_for_betting": False,
        })
    result = _finish(buckets)
    return {**{k: v for k, v in result.items() if k != "sports"},
            "sport": sport, **result["sports"][sport]}

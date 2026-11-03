"""Fail-closed V5 player-model calibration and provider slate audits.

These audits never approve models or represent a vendor sample as a full-slate
executable price feed. All data are read from immutable captured evidence.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from jabazi.models.train_player_props import promotion_decision
from jabazi.research.player_prospective import validation_report

CENTRAL = ZoneInfo("America/Chicago")


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except ValueError:
        return None


def calibration_audit(store):
    """Read-only gate evaluation; never mutate or promote artifacts."""
    prospective = validation_report(store)
    buckets = {(b["sport"], b["model_version"], b["market"]): b
               for b in prospective.get("buckets", [])}
    latest = {}
    for record in store.list_records("player_prop_model", 1000):
        artifact = record.get("payload") or {}
        key = (artifact.get("sport"), artifact.get("market"))
        if all(key) and key not in latest:
            latest[key] = artifact
    results = []
    for (sport, market), artifact in sorted(latest.items()):
        version = artifact.get("model_version")
        evidence = buckets.get((sport, version, market))
        if not version or not isinstance(artifact.get("validation"), dict):
            continue
        decision = promotion_decision(artifact, evidence)
        validation = decision.get("validation", {})
        checks = validation.get("promotion_checks", {})
        results.append({
            "sport": sport, "market": market, "model_version": version,
            "recorded_stage": artifact.get("stage", "SHADOW_ONLY"),
            "evaluated_stage": decision.get("stage", "SHADOW_ONLY"),
            "promotion_eligible": bool(validation.get("promotion_passed")),
            "checks": {name: bool(passed) for name, passed in checks.items()},
            "distribution_sample_count": (artifact.get("distribution_validation") or {}).get("n", 0),
            "prospective_sample_count": validation.get("prospective_sample_count", 0),
            "prospective_independent_events": validation.get("prospective_independent_event_count", 0),
            "prospective_brier": validation.get("prospective_brier"),
            "market_baseline_brier": validation.get("prospective_market_baseline_brier"),
            "prospective_ece": validation.get("prospective_ece"),
            "mean_clv_prob_points": validation.get("prospective_mean_clv_prob_points"),
        })
    return {
        "models": results, "model_count": len(results),
        "approved_count": sum(1 for x in results if x["promotion_eligible"]),
        "notice": "Approval requires calibrated, independently resolved prospective evidence; this read-only audit does not promote artifacts.",
    }


def full_slate_audit(store, *, now=None, slate_date=None):
    """Check whether archived vendor evidence covers EVERY scheduled game.

    Only vendor snapshots for the exact slate date and recent observation times
    qualify. A single sampled event or incomplete pagination never passes.
    """
    now = now or datetime.now(UTC)
    day = str(slate_date or now.astimezone(CENTRAL).date())
    results = {}
    for sport in ("nba", "nfl"):
        games = store.list_records("balldontlie_snapshot", 1000, entity=f"{sport}:games")
        props = store.list_records("balldontlie_snapshot", 1000, entity=f"{sport}:props")
        game_snapshot = None
        for record in games:
            payload = record.get("payload") or {}
            query = payload.get("query") or []
            queried_dates = [str(v) for k, v in query if k == "dates[]"] if isinstance(query, list) else []
            stamp = _timestamp(payload.get("observed_at"))
            if (day in queried_dates and stamp and timedelta(0) <= now-stamp <= timedelta(hours=6)):
                game_snapshot = payload
                break
        game_ids = set()
        games_complete = False
        if game_snapshot:
            vendor = game_snapshot.get("payload") or {}
            rows = vendor.get("data") or []
            game_ids = {row["id"] for row in rows
                        if isinstance(row, dict) and isinstance(row.get("id"), int)}
            meta = vendor.get("meta") or {}
            games_complete = (isinstance(rows, list)
                              and len(game_ids) == len(rows)
                              and isinstance(meta, dict)
                              and not meta.get("next_cursor"))
        covered = set()
        for record in props:
            payload = record.get("payload") or {}
            stamp = _timestamp(payload.get("observed_at"))
            if not stamp or not timedelta(0) <= now-stamp <= timedelta(minutes=5):
                continue
            query = payload.get("query") or []
            ids = [v for k, v in query if k == "game_id"] if isinstance(query, list) else []
            if len(ids) != 1:
                continue
            try:
                game_id = int(ids[0])
            except (ValueError, TypeError):
                continue
            vendor = payload.get("payload") or {}
            rows, meta = vendor.get("data"), vendor.get("meta")
            if (game_id in game_ids and isinstance(rows, list)
                    and isinstance(meta, dict) and not meta.get("next_cursor")
                    and all(isinstance(row, dict) for row in rows)):
                covered.add(game_id)
        missing = sorted(game_ids - covered)
        results[sport.upper()] = {
            "slate_date": day, "scheduled_games": len(game_ids),
            "covered_games": len(covered), "missing_game_ids": missing,
            "games_snapshot_complete": games_complete,
            "all_game_props_verified": bool(games_complete and game_ids and not missing),
            "executable_prices_verified": False,
            "model_calibration_verified": False,
            "notice": "Complete vendor capture is separate from live sportsbook execution and calibrated player-model approval.",
        }
    return {"sports": results, "slate_date": day}

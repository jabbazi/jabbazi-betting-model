"""Frozen prospective evaluation for player-prop models.

This module is intentionally separate from team-score prospective evaluation because
player markets settle from player outcomes, not final team scores.  It never places
or settles a wager; it grades immutable research forecasts.
"""
from __future__ import annotations

from datetime import UTC, datetime
import math

from sqlalchemy import select

from jabazi.persistence.store import digest, events

POLICY = "first-fresh-player-market-version-line-v1"


def _timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    return dt.astimezone(UTC)


def _records(store, kind):
    with store.engine.connect() as conn:
        rows = conn.execution_options(stream_results=True).execute(
            select(events.c.id, events.c.payload)
            .where(events.c.kind == kind)
            .order_by(events.c.occurred_at, events.c.id)
        )
        yield from rows.mappings()


def freeze_player_candidate(store, card, estimate, reliability, *, now=None):
    now = now or datetime.now(UTC)
    if not card.participant or card.in_play or card.starts_at is None or card.starts_at <= now:
        return False
    if card.market not in {
        "player_pass_yds", "player_pass_attempts", "player_pass_completions",
        "player_pass_tds", "player_rush_yds", "player_rush_attempts",
        "player_receptions", "player_reception_yds", "player_anytime_td",
        "pitcher_strikeouts", "pitcher_outs", "pitcher_hits_allowed",
        "pitcher_walks", "batter_hits", "batter_total_bases", "batter_home_runs",
        "batter_rbis", "batter_runs_scored", "batter_hits_runs_rbis", "batter_walks",
    }:
        return False
    if not all(
        0 <= (now - t).total_seconds() <= 120
        for t in (card.observed_at, card.source_timestamp)
    ):
        return False
    snapshot = estimate.feature_snapshot
    required = (
        "event_id", "participant", "features_available_at", "snapshot_id",
        "integrity",
    )
    if any(snapshot.get(k) is None for k in required):
        return False
    if snapshot["event_id"] != card.event_id or snapshot["participant"] != card.participant:
        return False
    if _timestamp(snapshot["features_available_at"]) > now:
        return False
    p = float(estimate.probability)
    market = float(card.consensus_probability)
    if not all(math.isfinite(x) and 0 < x < 1 for x in (p, market)):
        return False

    key = digest([
        POLICY, card.sport, card.event_id, card.participant, estimate.model_version,
        card.market, str(card.line), card.selection.lower(),
    ])
    payload = {
        "policy": POLICY,
        "sport": card.sport,
        "event_id": card.event_id,
        "participant": card.participant,
        "model_version": estimate.model_version,
        "market": card.market,
        "selection": card.selection.lower(),
        "line": None if card.line is None else float(card.line),
        "starts_at": card.starts_at.isoformat(),
        "predicted_at": now.isoformat(),
        "probability": p,
        "market_probability": market,
        "feature_snapshot_id": snapshot["snapshot_id"],
        "feature_snapshot": snapshot,
        "odds_snapshot": {
            "ids": list(card.quote_ids),
            "book": card.best_book,
            "decimal": str(card.best_decimal),
            "source_at": card.source_timestamp.isoformat(),
        },
        "reliability": reliability,
        "approved_for_betting": False,
    }
    with store.transaction() as conn:
        if conn.execute(select(events.c.id).where(events.c.id == key)).first():
            return False
        return store._append(conn, "player_prospective_forecast", card.event_id, payload, key)


def archive_player_result(
    store,
    *,
    sport,
    event_id,
    participant,
    market,
    observed_value,
    starts_at,
    observed_at,
    source_checksum,
    result_status="final",
    closing_no_vig_probability=None,
):
    if observed_at.tzinfo is None or not source_checksum:
        raise ValueError("Player result provenance required")
    value = float(observed_value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Invalid player result")
    start = _timestamp(starts_at)
    if start >= observed_at:
        raise ValueError("Result cannot predate event")
    closing = None
    if closing_no_vig_probability is not None:
        closing = float(closing_no_vig_probability)
        if not 0 < closing < 1:
            raise ValueError("Invalid closing probability")
    payload = {
        "sport": sport,
        "event_id": str(event_id),
        "participant": participant,
        "market": market,
        "observed_value": value,
        "starts_at": start.isoformat(),
        "observed_at": observed_at.isoformat(),
        "source_checksum": source_checksum,
        "result_status": result_status,
        "closing_no_vig_probability": closing,
    }
    key = digest(["player_prospective_result", payload])
    with store.transaction() as conn:
        if conn.execute(select(events.c.id).where(events.c.id == key)).first():
            return False
        return bool(store._append(
            conn, "player_prospective_result",
            f"{sport}|{event_id}|{participant}|{market}",
            payload, key,
        ))


def _outcome(forecast, result):
    if any(
        forecast[k] != result[k]
        for k in ("sport", "event_id", "participant", "market")
    ):
        raise ValueError("Player result identity mismatch")
    if abs((_timestamp(forecast["starts_at"]) - _timestamp(result["starts_at"])).total_seconds()) > 60:
        raise ValueError("Player result kickoff mismatch")
    if _timestamp(forecast["predicted_at"]) >= _timestamp(result["starts_at"]):
        raise ValueError("Forecast was not pregame")
    if result.get("result_status") in {"dnp", "void"}:
        return "EXCLUDE"
    if result.get("result_status") != "final":
        raise ValueError("Unresolved player result")
    observed = float(result["observed_value"])
    side = forecast["selection"]
    line = forecast["line"]
    if side in {"yes", "no"}:
        hit = observed > 0
        return int(hit if side == "yes" else not hit)
    if line is None:
        raise ValueError("Threshold result missing line")
    if observed == float(line):
        return "PUSH"
    if side == "over":
        return int(observed > float(line))
    if side == "under":
        return int(observed < float(line))
    raise ValueError("Unknown player market side")


def _metrics(pairs):
    if not pairs:
        return {"n": 0, "brier": None, "log_loss": None}
    n = len(pairs)
    brier = sum((p-y)**2 for p,y in pairs) / n
    log_loss = -sum(
        y*math.log(max(p,1e-12)) + (1-y)*math.log(max(1-p,1e-12))
        for p,y in pairs
    ) / n
    return {"n": n, "brier": brier, "log_loss": log_loss}


def _ece(pairs, bins=10):
    if not pairs:
        return None
    total = len(pairs)
    score = 0.0
    for index in range(bins):
        low, high = index/bins, (index+1)/bins
        bucket = [(p,y) for p,y in pairs if low <= p < high or (index == bins-1 and p == 1)]
        if not bucket:
            continue
        score += len(bucket)/total * abs(
            sum(p for p,_ in bucket)/len(bucket) - sum(y for _,y in bucket)/len(bucket)
        )
    return score


def validation_report(store):
    latest = {}
    for row in _records(store, "player_prospective_result"):
        result = row["payload"]
        latest[(result["sport"], result["event_id"], result["participant"], result["market"])] = result

    groups = {}
    for row in _records(store, "player_prospective_forecast"):
        f = row["payload"]
        key = (f["sport"], f["model_version"], f["market"])
        g = groups.setdefault(key, {
            "frozen": 0, "pending": 0, "pushes": 0, "excluded": 0,
            "identity_failures": 0, "pairs": [], "market_pairs": [], "clv": [],
            "data_health_failures": 0,
        })
        g["frozen"] += 1
        result = latest.get((f["sport"], f["event_id"], f["participant"], f["market"]))
        if result is None:
            g["pending"] += 1
            continue
        try:
            outcome = _outcome(f, result)
        except (ValueError, KeyError, TypeError):
            g["identity_failures"] += 1
            continue
        if outcome == "EXCLUDE":
            g["excluded"] += 1
            continue
        if outcome == "PUSH":
            g["pushes"] += 1
            continue
        y = int(outcome)
        g["pairs"].append((float(f["probability"]), y))
        g["market_pairs"].append((float(f["market_probability"]), y))
        if result.get("closing_no_vig_probability") is not None:
            # Positive means the market moved toward the forecasted side.
            g["clv"].append(
                100 * (
                    float(result["closing_no_vig_probability"])
                    - float(f["market_probability"])
                )
            )
        integrity = f.get("feature_snapshot", {}).get("integrity", {})
        required = (
            "event_identity", "player_identity", "fresh_features", "schema",
            "role", "availability", "injuries", "no_duplicate_event",
        )
        if not all(integrity.get(k) is True for k in required):
            g["data_health_failures"] += 1

    buckets = []
    for (sport, version, market), g in sorted(groups.items()):
        model_pairs = g.pop("pairs")
        market_pairs = g.pop("market_pairs")
        clv = g.pop("clv")
        model = _metrics(model_pairs)
        market_metrics = _metrics(market_pairs)
        buckets.append({
            "sport": sport,
            "model_version": version,
            "market": market,
            **g,
            "sample_count": model["n"],
            "brier": model["brier"],
            "log_loss": model["log_loss"],
            "market_baseline_brier": market_metrics["brier"],
            "market_baseline_log_loss": market_metrics["log_loss"],
            "ece": _ece(model_pairs),
            "clv_sample_count": len(clv),
            "mean_clv_prob_points": sum(clv)/len(clv) if clv else None,
        })
    return {
        "policy": POLICY,
        "generated_at": datetime.now(UTC).isoformat(),
        "buckets": buckets,
    }

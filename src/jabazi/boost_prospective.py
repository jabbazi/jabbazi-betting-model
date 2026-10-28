"""Immutable NBA/NHL exact-ticket prospective evidence capture (research only).

Operator-invoked functions, NOT public routes, automatic wagering, or model
promotion. External source authenticity and sportsbook settlement must still be
independently reviewed. Never generate a joint probability from leg prices.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Mapping

from sqlalchemy import select

from jabazi.persistence.store import digest, events

SPORTS = frozenset({"basketball_nba", "icehockey_nhl"})
FORECAST = "boost_joint_forecast"
RESULT = "boost_joint_result"
MAX_SOURCE_AGE = timedelta(minutes=10)


def _at(value, name):
    if not isinstance(value, str):
        raise ValueError(f"Missing {name}")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid {name}") from None
    if instant.utcoffset() is None:
        raise ValueError(f"Naive timestamp: {name}")
    return instant.astimezone(UTC)


def _now(value):
    instant = value or datetime.now(UTC)
    if not isinstance(instant, datetime) or instant.utcoffset() is None:
        raise ValueError("Server observation time must be timezone-aware")
    return instant.astimezone(UTC)


def _number(value, name, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"Invalid {name}") from None
    if not isfinite(number) or (not 0 < number < 1 if positive else number < 0):
        raise ValueError(f"Invalid {name}")
    return number


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(f"Invalid {name}")
    return value.strip()


def _leg(value):
    if not isinstance(value, Mapping):
        raise ValueError("Invalid leg")
    keys = ("leg_id", "player_id", "market", "side")
    leg = {key: _text(value.get(key), key) for key in keys}
    if leg["side"] not in {"over", "under", "yes", "no"}:
        raise ValueError("Invalid leg side")
    raw = value.get("line")
    if leg["side"] in {"over", "under"}:
        leg["line"] = _number(raw, "leg line")
    elif raw is not None:
        raise ValueError("Yes/no legs do not accept a threshold")
    else:
        leg["line"] = None
    return leg


def _snapshot(source, *, now, name):
    if not isinstance(source, Mapping) or not isinstance(source.get("payload"), Mapping):
        raise ValueError(f"Missing {name} snapshot payload")
    stamp = _at(source.get("observed_at"), name + " observed_at")
    if not timedelta(0) <= now - stamp <= MAX_SOURCE_AGE:
        raise ValueError(f"Stale/future {name} snapshot")
    provider = _text(source.get("provider"), name + " provider")
    payload = dict(source["payload"])
    return {
        "provider": provider,
        "observed_at": stamp.isoformat(),
        "payload": payload,
        # SHA refers to the exact source object, never an owner-typed claim.
        "sha256": digest([provider, stamp.isoformat(), payload]),
    }


def _forecast_id(sport, event_id, ticket_id, model_version):
    return digest(["boost_joint_v1", sport, event_id, ticket_id, model_version])


def freeze_joint_ticket(store, ticket, *, observed_at=None):
    """Freeze one real supplied exact ticket atomically in the existing event store.

    Only authorized internal callers should invoke this. A caller cannot
    retroactively set the prediction/freeze time: both are server-observed.
    This function cannot certify that the upstream model actually fitted,
    that a sportsbook quote is executable, or that sources are authentic.
    """
    now = _now(observed_at)
    if not isinstance(ticket, Mapping) or ticket.get("sport") not in SPORTS:
        raise ValueError("Unsupported joint ticket sport")
    sport = ticket["sport"]
    event = _text(ticket.get("event_id"), "event_id")
    ticket_id = _text(ticket.get("ticket_id"), "ticket_id")
    version = _text(ticket.get("model_version"), "model_version")
    starts = _at(ticket.get("starts_at"), "starts_at")
    if not now < starts:
        raise ValueError("Cannot freeze after event begins")
    trained = _at(ticket.get("trained_through"), "trained_through")
    test = _at(ticket.get("test_start"), "test_start")
    prospective = _at(ticket.get("prospective_start"), "prospective_start")
    if not trained < test < prospective:
        raise ValueError("Invalid model training/test/prospective boundaries")
    if ticket.get("split") != "prospective" or starts < prospective:
        raise ValueError("Only genuinely prospective ticket forecasts are accepted")
    probability = _number(ticket.get("joint_probability"), "joint probability", positive=True)
    legs_raw = ticket.get("legs")
    if not isinstance(legs_raw, list) or not 2 <= len(legs_raw) <= 4:
        raise ValueError("Exact 2-4 legs required")
    legs = [_leg(item) for item in legs_raw]
    if len({x["leg_id"] for x in legs}) != len(legs):
        raise ValueError("Duplicate ticket leg identity")
    if len({(x["player_id"], x["market"], x["line"]) for x in legs}) != len(legs):
        raise ValueError("Contradictory same player/market/line legs")
    model_source = _snapshot(ticket.get("model_source"), now=now, name="model")
    model_evidence = model_source["payload"]
    if (model_evidence.get("event_id") != event
            or model_evidence.get("ticket_id") != ticket_id
            or model_evidence.get("model_version") != version
            or model_evidence.get("joint_probability") != probability
            or model_evidence.get("leg_ids") != [leg["leg_id"] for leg in legs]):
        raise ValueError("Frozen model evidence does not match exact ticket")
    features_at = _at(model_source["payload"].get("features_available_at"), "features_available_at")
    if features_at > now or features_at > _at(model_source["observed_at"], "model observed_at"):
        raise ValueError("Future features in model evidence")
    market_source = None
    market_probability = None
    if ticket.get("market_source") is not None:
        market_source = _snapshot(ticket["market_source"], now=now, name="market")
        market = market_source["payload"]
        if market.get("baseline_kind") != "independently_quoted_combined_ticket":
            raise ValueError("Exact combined-ticket market baseline required")
        if market.get("event_id") != event or market.get("ticket_id") != ticket_id:
            raise ValueError("Combined quote does not match ticket")
        if market.get("leg_ids") != [leg["leg_id"] for leg in legs]:
            raise ValueError("Combined market quote leg identity mismatch")
        if not _text(market.get("book"), "book"):
            raise ValueError("Book is required")
        market_probability = _number(market.get("no_vig_probability"), "combined market probability", positive=True)
    payload = {
        "policy": "boost_joint_prospective_v1",
        "sport": sport, "event_id": event, "ticket_id": ticket_id,
        "model_version": version, "split": "prospective",
        "trained_through": trained.isoformat(),
        "test_start": test.isoformat(),
        "prospective_start": prospective.isoformat(),
        "starts_at": starts.isoformat(),
        "predicted_at": now.isoformat(),
        "forecast_frozen_at": now.isoformat(),
        "features_available_at": features_at.isoformat(),
        "joint_probability": probability, "legs": legs,
        "model_source": model_source,
        "market_source": market_source,
        "market_probability": market_probability,
        "approved_for_betting": False,
    }
    key = _forecast_id(sport, event, ticket_id, version)
    with store.transaction() as conn:
        # Conflicting retries reject instead of rewriting a frozen probability.
        created = store._append(conn, FORECAST, event, payload, key)
    return {"created": created, "forecast_id": key, "state": "RESEARCH_ONLY"}


def archive_joint_outcome(store, *, forecast_id, leg_results, result_source,
                          observed_at=None):
    """Resolve an existing frozen ticket; never accept an owner-supplied win flag.

    Computes a binary outcome only when *every* leg is final, unpushed,
    correctly identified and source-supported. All other tickets are excluded.
    """
    now = _now(observed_at)
    if not isinstance(forecast_id, str) or len(forecast_id) != 64:
        raise ValueError("Invalid forecast ID")
    if not isinstance(leg_results, list):
        raise ValueError("Leg results required")
    result_snapshot = _snapshot(result_source, now=now, name="result")
    if _at(result_snapshot["observed_at"], "result observed_at") > now:
        raise ValueError("Result after observation")
    with store.transaction() as conn:
        record = conn.execute(
            select(events).where(events.c.id == forecast_id,
                                 events.c.kind == FORECAST)
        ).mappings().first()
        if record is None:
            raise ValueError("Frozen prospective forecast not found")
        frozen = record["payload"]
        source_payload = result_snapshot["payload"]
        if (source_payload.get("event_id") != frozen["event_id"]
                or source_payload.get("ticket_id") != frozen["ticket_id"]
                or source_payload.get("forecast_id") != forecast_id
                or source_payload.get("leg_results") != leg_results):
            raise ValueError("Archived result source does not match resolved legs")
        start = _at(frozen["starts_at"], "starts_at")
        if now <= start or _at(result_snapshot["observed_at"], "result observed_at") <= start:
            raise ValueError("Event has not finished")
        expected = {leg["leg_id"]: leg for leg in frozen["legs"]}
        if len(leg_results) != len(expected):
            raise ValueError("Missing or extra resolved leg")
        seen = set()
        states = []
        for observed in leg_results:
            if not isinstance(observed, Mapping):
                raise ValueError("Invalid resolved leg")
            leg_id = observed.get("leg_id")
            if leg_id not in expected or leg_id in seen:
                raise ValueError("Wrong or duplicate resolved leg")
            seen.add(leg_id)
            leg = expected[leg_id]
            for identity in ("player_id", "market"):
                if observed.get(identity) != leg[identity]:
                    raise ValueError("Resolved leg identity mismatch")
            status = observed.get("status")
            if status in {"void", "dnp", "canceled", "push"}:
                states.append("EXCLUDE")
                continue
            if status != "final":
                raise ValueError("Unverified settlement status")
            value = _number(observed.get("observed_value"), "observed_value")
            side, line = leg["side"], leg["line"]
            if side in {"yes", "no"}:
                states.append((value > 0) if side == "yes" else (value == 0))
            elif value == line:
                states.append("EXCLUDE")
            elif side == "over":
                states.append(value > line)
            else:
                states.append(value < line)
        outcome = None if "EXCLUDE" in states else int(all(states))
        result = {
            "policy": "boost_joint_outcome_v1",
            "forecast_id": forecast_id, "sport": frozen["sport"],
            "event_id": frozen["event_id"], "ticket_id": frozen["ticket_id"],
            "model_version": frozen["model_version"],
            "status": "EXCLUDED" if outcome is None else "FINAL",
            "outcome": outcome, "result_snapshot": result_snapshot,
            "result_observed_at": now.isoformat(),
            "approved_for_betting": False,
        }
        key = digest(["boost_joint_outcome_v1", forecast_id])
        created = store._append(conn, RESULT, frozen["event_id"], result, key)
    return {"created": created, "status": result["status"],
            "outcome": outcome, "research_only": True}


def audit_ready_rows(store, *, event_limit=100000):
    """Reconcile immutable records without fabricating missing evidence.

    Return only strictly complete genuine-looking rows for the separate
    provenance audit. Caller must still authenticate source receipts.
    """
    if not 1 <= event_limit <= 100000:
        raise ValueError("Invalid evidence limit")
    with store.engine.connect() as conn:
        forecasts = conn.execute(
            select(events.c.payload, events.c.id)
            .where(events.c.kind == FORECAST)
            .order_by(events.c.occurred_at, events.c.id)
            .limit(event_limit + 1)
        ).mappings().all()
        results = conn.execute(
            select(events.c.payload)
            .where(events.c.kind == RESULT)
            .order_by(events.c.occurred_at, events.c.id)
            .limit(event_limit + 1)
        ).mappings().all()
    if len(forecasts) > event_limit or len(results) > event_limit:
        raise ValueError("Archive limit exceeded; no partial audit")
    by_forecast = {r["payload"]["forecast_id"]: r["payload"] for r in results}
    rows = []
    for item in forecasts:
        f = item["payload"]
        r = by_forecast.get(item["id"])
        if not r or r["status"] != "FINAL" or f["market_source"] is None:
            continue
        rows.append({
            "sport": f["sport"], "event_id": f["event_id"],
            "ticket_id": f["ticket_id"], "model_version": f["model_version"],
            "split": f["split"], "probability": f["joint_probability"],
            "outcome": r["outcome"],
            "predicted_at": f["predicted_at"],
            "forecast_frozen_at": f["forecast_frozen_at"],
            "starts_at": f["starts_at"],
            "result_observed_at": r["result_observed_at"],
            "features_available_at": f["features_available_at"],
            "trained_through": f["trained_through"],
            "test_start": f["test_start"],
            "prospective_start": f["prospective_start"],
            "forecast_snapshot_sha256": f["model_source"]["sha256"],
            "result_snapshot_sha256": r["result_snapshot"]["sha256"],
            "market_snapshot_sha256": f["market_source"]["sha256"],
            "market_probability": f["market_probability"],
            "market_observed_at": f["market_source"]["observed_at"],
            "market_baseline_kind": "independently_quoted_combined_ticket",
        })
    return rows

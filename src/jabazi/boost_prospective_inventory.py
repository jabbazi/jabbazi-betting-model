"""Aggregate custody inventory for NBA/NHL joint-prospective research events.

This is an operator-only, read-only surface over the *existing* append-only
platform event table. It never exposes event/player/ticket IDs or licensed
bookmaker data; counts are not calibration or promotion.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select

from jabazi.persistence.store import digest, events
from jabazi.boost_prospective import FORECAST, RESULT, SPORTS


def _read(store, limit):
    with store.engine.connect() as conn:
        return conn.execute(
            select(events.c.id, events.c.kind, events.c.payload, events.c.sha256)
            .where(events.c.kind.in_((FORECAST, RESULT)))
            .order_by(events.c.occurred_at, events.c.id)
            .limit(limit + 1)
        ).mappings().all()


def capture_inventory(store, *, limit=100000):
    """Classify all captured evidence without silently truncating or approving it.

    Validate the content-addressed DB payload and nested source checksums.
    These digests detect changes, not whether the *external* source is genuine.
    Any inconsistency prevents the CLI from presenting strict audit scores.
    """
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("Invalid inventory cap")
    records = _read(store, limit)
    if len(records) > limit:
        raise ValueError("Archive inventory cap exceeded: no partial evidence report")
    totals = {
        sport: Counter({
            "frozen": 0, "pending_result": 0, "settled_final": 0,
            "settled_excluded": 0, "missing_market_baseline": 0,
            "fully_resolved_with_baseline": 0, "invalid_evidence": 0,
        }) for sport in sorted(SPORTS)
    }
    forecasts, results = {}, {}
    invalid_db_records = 0
    for entry in records:
        payload = entry["payload"]
        if not isinstance(payload, dict) or digest(payload) != entry["sha256"]:
            invalid_db_records += 1
            continue
        kind = entry["kind"]
        if kind == FORECAST:
            forecasts[entry["id"]] = payload
        elif kind == RESULT:
            if not isinstance(payload.get("forecast_id"), str):
                invalid_db_records += 1
                continue
            if payload["forecast_id"] in results:
                invalid_db_records += 1
                continue
            results[payload["forecast_id"]] = payload
    for fid, f in forecasts.items():
        sport = f.get("sport")
        if sport not in totals:
            invalid_db_records += 1
            continue
        counts = totals[sport]
        counts["frozen"] += 1
        market = f.get("market_source")
        if market is None:
            counts["missing_market_baseline"] += 1
        sources = [f.get("model_source")]
        if market is not None:
            sources.append(market)
        invalid = False
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("payload"), dict):
                invalid = True
                break
            try:
                canonical = digest([source["provider"], source["observed_at"], source["payload"]])
            except (KeyError, TypeError, ValueError):
                invalid = True
                break
            if source.get("sha256") != canonical:
                invalid = True
                break
        r = results.get(fid)
        if r is None:
            counts["pending_result"] += 1
        else:
            source = r.get("result_snapshot")
            if not isinstance(source, dict) or not isinstance(source.get("payload"), dict):
                invalid = True
            else:
                try:
                    canonical = digest([source["provider"], source["observed_at"], source["payload"]])
                    if source.get("sha256") != canonical:
                        invalid = True
                except (KeyError, TypeError, ValueError):
                    invalid = True
            if (r.get("sport") != sport or r.get("event_id") != f.get("event_id")
                    or r.get("ticket_id") != f.get("ticket_id")
                    or r.get("model_version") != f.get("model_version")):
                invalid = True
            if r.get("status") == "FINAL" and type(r.get("outcome")) is int and r["outcome"] in (0, 1):
                counts["settled_final"] += 1
                if market is not None and not invalid:
                    counts["fully_resolved_with_baseline"] += 1
            elif r.get("status") == "EXCLUDED" and r.get("outcome") is None:
                counts["settled_excluded"] += 1
            else:
                invalid = True
        if invalid:
            counts["invalid_evidence"] += 1
    orphan_results = len(set(results) - set(forecasts))
    integrity_failures = invalid_db_records + orphan_results + sum(
        x["invalid_evidence"] for x in totals.values()
    )
    return {
        "status": "INTEGRITY_BLOCKED" if integrity_failures else (
            "NO_EVIDENCE" if not forecasts else "RESEARCH_ONLY"
        ),
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "sports": {sport: dict(counts) for sport, counts in totals.items()},
        "records_examined": len(records),
        "orphan_results": orphan_results,
        "integrity_failures": integrity_failures,
        "independent_external_source_authenticity": "NOT_VERIFIED",
        "nba_nhl_prospective_calibration": "NOT_APPROVED",
        "approved_for_betting": False,
        "note": "A record's hash does not verify the external provider or bookmaker.",
    }

"""Read-only owner research view. No model approvals or publishing side effects."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from .discord_sheets import SPORTS


def age_seconds(value, now):
    try:
        at = datetime.fromisoformat(value)
        if at.tzinfo is None:
            return None
        age = (now - at).total_seconds()
        return age if age >= 0 else None
    except (TypeError, ValueError):
        return None


def probability(value):
    try:
        number = Decimal(str(value))
        return str(number) if number.is_finite() and 0 < number < 1 else None
    except (InvalidOperation, ValueError):
        return None


def review_snapshot(store, *, sport=None, page=1, now=None):
    now = now or datetime.now(UTC)
    records = store.list_records("research_sheet", 1, entity="latest_scan")
    base = {
        "generated_at": now.isoformat(),
        "betting_enabled": False,
        "page": page,
        "page_size": 25,
        "total": 0,
        "cards": [],
    }
    if not records:
        return base | {"status": "UNAVAILABLE", "snapshot_id": None}
    record = records[0]
    payload = record["payload"]
    age = age_seconds(payload.get("completed_at"), now)
    status = (
        "DATA_UNHEALTHY"
        if payload.get("healthy") is not True
        else "STALE_DATA"
        if age is None or age > 10800
        else "RESEARCH_ONLY"
    )
    rows = [r for r in payload.get("rows", []) if not sport or r.get("sport") == SPORTS[sport]]
    cards = []
    for row in rows[(page - 1) * 25 : page * 25]:
        price_age = age_seconds(row.get("price_time_utc"), now)
        model = probability(row.get("research_probability")) if row.get("model_version") else None
        blocks = ["No production-approved model; research only"]
        if status != "RESEARCH_ONLY":
            blocks.append(status)
        if price_age is None or price_age > 120:
            blocks.append("Price is not verified fresh; refresh required before execution")
        if model is None:
            blocks.append("Independent model probability unavailable")
        start_age = age_seconds(row.get("starts_at_utc"), now)
        if start_age is not None:
            blocks.append("Event has started; pregame snapshot only")
        cards.append(
            {
                **{
                    key: row.get(key)
                    for key in (
                        "sport",
                        "event",
                        "market",
                        "participant",
                        "selection",
                        "line",
                        "book",
                        "decimal_odds",
                        "price_time_utc",
                        "starts_at_utc",
                        "model_version",
                        "reason",
                    )
                },
                "market_no_vig_probability": probability(row.get("market_no_vig_probability")),
                "research_probability": model,
                "probability_edge": row.get("probability_edge") if model else None,
                "expected_roi": row.get("expected_roi") if model else None,
                "uncertainty": row.get("uncertainty") if model else None,
                "decision": "WATCH" if status == "RESEARCH_ONLY" else status,
                "blockers": blocks,
                "stake": None,
                "maximum_playable_price": None,
            }
        )
    return base | {
        "status": status,
        "snapshot_id": record["id"],
        "snapshot_time": payload.get("completed_at"),
        "total": len(rows),
        "truncated": bool(payload.get("truncated")),
        "cards": cards,
    }

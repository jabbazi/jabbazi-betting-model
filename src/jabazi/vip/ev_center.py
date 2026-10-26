"""Evidence-gated +EV research for the existing authenticated VIP terminal.

This is a research view, not an official picks publisher. No market consensus
or experimental model is silently promoted to an independent betting edge.
"""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .data import age_ok, number, timestamp

CENTRAL = ZoneInfo("America/Chicago")
BLOCKED = {"QUARANTINED", "INVALIDATED", "SAFETY REVIEW", "PASS"}


def ev_center(rows, *, now=None, slate_date=None, sport="", market="", book="",
              min_ev=0.03, min_probability=0.0, max_quote_age=300, limit=100):
    now = now or datetime.now(UTC)
    day = slate_date or now.astimezone(CENTRAL).date()
    if not 0 <= min_ev <= 1 or not 0 <= min_probability <= 1:
        raise ValueError("Probability and EV filters must be in [0,1]")
    if not 1 <= max_quote_age <= 300 or not 1 <= limit <= 100:
        raise ValueError("Invalid freshness or page limit")
    qualified = []
    excluded = {"not_current": 0, "unverified": 0, "not_approved": 0,
                "below_threshold": 0}
    for r in rows:
        if ((sport and r.get("sport") != sport.upper())
                or (market and r.get("market") != market)
                or (book and str(r.get("book") or "").casefold() != book.casefold())):
            continue
        start = timestamp(r.get("starts_at"))
        if (not start or start <= now or start.astimezone(CENTRAL).date() != day
                or r.get("lifecycle") != "UPCOMING"):
            excluded["not_current"] += 1
            continue
        d = number(r.get("decimal"))
        # An approved stage alone does not make an uncalibrated point estimate
        # suitable for the official price-aware research feed.
        p = number(r.get("calibrated_probability"))
        if (r.get("status") in BLOCKED or not r.get("fresh")
                or r.get("data_health") != "HEALTHY"
                or not age_ok(r.get("price_at"), now, max_quote_age)
                or d is None or d <= 1 or p is None or not 0 < p < 1
                or not r.get("book") or not r.get("model_version")):
            excluded["unverified"] += 1
            continue
        if r.get("model_stage") != "PRODUCTION_APPROVED":
            excluded["not_approved"] += 1
            continue
        push = number(r.get("push_probability")) or 0.0
        if push < 0 or p + push > 1:
            excluded["unverified"] += 1
            continue
        ev = p * d + push - 1
        if ev < min_ev or p < min_probability:
            excluded["below_threshold"] += 1
            continue
        market_p = number(r.get("market_probability"))
        qualified.append({
            "id": r.get("id"), "sport": r["sport"], "event": r.get("event"),
            "event_id": r.get("event_id"), "starts_at": r.get("starts_at"),
            "player": r.get("player"), "selection": r.get("selection"),
            "market": r.get("market"), "line": r.get("line"),
            "book": r.get("book"), "decimal": d, "price_at": r.get("price_at"),
            "model_probability": p, "market_probability": market_p,
            "fair_decimal": (1 - push) / p, "break_even_probability": (1 - push) / d,
            "ev": ev, "expected_profit_per_50": 50 * ev,
            "play_to_decimal": (1 - push + min_ev) / p,
            "model_stage": r["model_stage"], "model_version": r["model_version"],
            "data_health": r["data_health"], "uncertainty": r.get("uncertainty"),
            "status": "WATCH", "approved_for_betting": False,
            "probability_basis": "MODEL",
            "notice": "Research only. Production model status does not independently verify execution or authorize a wager.",
        })
    qualified.sort(key=lambda x: (-x["ev"], x["starts_at"], str(x["id"])))
    return {
        "date": day.isoformat(), "rows": qualified[:limit], "matching": len(qualified),
        "excluded": excluded, "min_ev": min_ev, "min_probability": min_probability,
        "max_quote_age_seconds": max_quote_age,
        "notice": "Only fresh production-approved model research is eligible. Missing or unsupported markets return no results. No wagers are authorized.",
    }

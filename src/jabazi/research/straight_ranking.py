"""Fail-closed straight selection from verified, saved player-model quotes.

Pure research helper: does not fetch odds, infer models, place bets, or promote
validation stages. Production callers must supply independently verified rows.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from collections import Counter

SPORTS = frozenset({"basketball_nba", "americanfootball_nfl", "icehockey_nhl", "baseball_mlb"})


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo is not None else None
    except ValueError:
        return None


def _decimal_price(row):
    if row.get("decimal_odds") is not None:
        d = _number(row["decimal_odds"])
        return d if d is not None and d > 1 else None
    odds = _number(row.get("american_odds"))
    if odds is None or -100 < odds < 100:
        return None
    return 1 + (odds / 100 if odds > 0 else 100 / (-odds))


def rank_verified_straights(rows, *, now=None, max_age_seconds=300, minimum_ev="0.02"):
    """Return at most one validated straight, or PASS, plus separate research counts.

    Model probabilities and odds must be genuine, exact-line, identity-checked,
    fresh observations. No unapproved model can produce a recommended straight.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None or max_age_seconds <= 0:
        raise ValueError("Invalid clock or freshness configuration")
    now = now.astimezone(UTC)
    floor = _number(minimum_ev)
    if floor is None or floor < 0:
        raise ValueError("Invalid minimum expected value")
    rejected = Counter()
    qualifying = {}
    research_only = 0
    for row in rows:
        if not isinstance(row, dict):
            rejected["INVALID_ROW"] += 1
            continue
        sport = row.get("sport")
        event = str(row.get("event_id") or "").strip()
        participant = str(row.get("participant") or "").strip()
        market = str(row.get("market") or "").strip()
        side = str(row.get("side") or "").lower()
        book = str(row.get("sportsbook") or "").strip()
        line = _number(row.get("line"))
        p = _number(row.get("model_probability"))
        push = _number(row.get("push_probability", 0))
        odds = _decimal_price(row)
        at = _instant(row.get("observed_at"))
        start = _instant(row.get("starts_at"))
        if (sport not in SPORTS or not all((event, participant, market, book))
                or side not in {"over", "under", "yes", "no"}
                or line is None or p is None or push is None or odds is None
                or not (0 < p < 1 and 0 <= push < 1 and p + push <= 1)
                or not row.get("model_version")
                or row.get("exact_line_verified") is not True
                or row.get("identity_verified") is not True):
            rejected["INCOMPLETE_OR_UNVERIFIED"] += 1
            continue
        if (row.get("price_is_current") is not True or at is None or start is None
                or not (0 <= (now - at).total_seconds() <= max_age_seconds)
                or start <= now):
            rejected["STALE_OR_INELIGIBLE"] += 1
            continue
        approved = (row.get("model_stage") == "PRODUCTION_APPROVED"
                    and row.get("approved_for_betting") is True
                    and row.get("validation_passed") is True)
        if not approved:
            research_only += 1
            continue
        ev = p * (odds - 1) - (1 - p - push)
        if ev < floor:
            rejected["BELOW_EDGE_FLOOR"] += 1
            continue
        key = (sport, event, participant.lower(), market, side, str(line.normalize()))
        candidate = {
            "sport": sport, "event_id": event, "participant": participant,
            "market": market, "side": side, "line": str(line),
            "sportsbook": book, "decimal_odds": str(odds),
            "model_probability": str(p), "push_probability": str(push),
            "expected_net_return_per_unit": str(ev),
            "observed_at": at.isoformat(), "starts_at": start.isoformat(),
            "model_version": str(row["model_version"]),
        }
        old = qualifying.get(key)
        if old is None or ev > Decimal(old["expected_net_return_per_unit"]):
            qualifying[key] = candidate
    ranked = sorted(qualifying.values(), key=lambda x: (
        -Decimal(x["expected_net_return_per_unit"]), x["sport"], x["event_id"],
        x["participant"], x["market"], x["side"]))
    return {
        "status": "QUALIFYING_STRAIGHT" if ranked else "PASS",
        "best_straight": ranked[0] if ranked else None,
        "qualifying_distinct_selections": len(ranked),
        "research_only_rows": research_only,
        "rejection_counts": dict(sorted(rejected.items())),
        "betting_enabled": False,
        "note": "Research gate only; no wagering execution or automatic model approval.",
    }

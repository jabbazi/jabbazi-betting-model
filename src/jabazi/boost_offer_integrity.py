"""Vendor-neutral integrity checks for licensed BALLDONTLIE prop quotes.

A quote is NOT an executable bookmaker ticket, model prediction or joint
probability. Vendor row IDs are ephemeral; canonical identities use the
game, player, sportsbook, market, line and market type instead.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Mapping


def _positive_int(value):
    return type(value) is int and value > 0


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    return result if result.is_finite() else None


def _american_odds(value):
    # A quoted side requires a numeric American price with nonzero sign.
    return type(value) is int and (value <= -100 or value >= 100)


def inspect_prop_offer(row: Mapping, game_id: int, *, observed_at: datetime,
                       max_age: timedelta = timedelta(minutes=15)):
    """Return (semantic_identity, issue), not a model probability.

    updated_at is the vendor's last refresh time, NOT a promise the odds
    still exist at the book. No separate sportsbook confirmation is implied.
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Observation timestamp must be timezone-aware")
    if max_age <= timedelta(0):
        raise ValueError("Invalid freshness window")
    if not isinstance(row, Mapping) or not _positive_int(row.get("id")):
        return None, "INVALID_PROP_ID"
    if row.get("game_id") != game_id:
        return None, "FOREIGN_GAME_ID"
    if not _positive_int(row.get("player_id")):
        return None, "INVALID_PLAYER_ID"
    vendor, prop_type = row.get("vendor"), row.get("prop_type")
    if not all(isinstance(x, str) and x.strip() for x in (vendor, prop_type)):
        return None, "INVALID_OFFER_LABELS"
    line = _decimal(row.get("line_value"))
    if line is None or line < 0:
        return None, "INVALID_PROP_LINE"
    market = row.get("market")
    if not isinstance(market, Mapping):
        return None, "INVALID_MARKET"
    kind = market.get("type")
    if kind == "over_under":
        if not any(_american_odds(market.get(k)) for k in ("over_odds", "under_odds")):
            return None, "INVALID_MARKET_PRICE"
    elif kind == "milestone":
        if not _american_odds(market.get("odds")):
            return None, "INVALID_MARKET_PRICE"
    else:
        return None, "INVALID_MARKET_TYPE"
    stamp = row.get("updated_at")
    if not isinstance(stamp, str):
        return None, "MISSING_VENDOR_TIMESTAMP"
    try:
        updated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None, "INVALID_VENDOR_TIMESTAMP"
    if updated.tzinfo is None or updated.utcoffset() is None:
        return None, "INVALID_VENDOR_TIMESTAMP"
    age = observed_at.astimezone(UTC) - updated.astimezone(UTC)
    if not timedelta(0) <= age <= max_age:
        return None, "STALE_OR_FUTURE_VENDOR_QUOTE"
    return (game_id, row["player_id"], vendor.strip().lower(),
            prop_type.strip(), str(line.normalize()), kind), None

"""Validate promotion terms before pricing; a boost never bypasses wager gates."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from .pricing import decimal_price, number, probability, profit_boost, roi, bonus_bet_cash_value


@dataclass(frozen=True)
class Promotion:
    book: str
    kind: str
    expires_at: datetime
    max_stake: D
    min_raw_decimal: D = D(1)
    min_legs: int = 1
    boost: D = D(0)
    sports: frozenset = frozenset()
    markets: frozenset = frozenset()
    stacking_allowed: bool = False
    void_rules_verified: bool = False


def evaluate(
    promo, *, book, price, p, stake, legs, now, sport, markets, base_qualified, stacked=False
):
    price = decimal_price(price)
    p = probability(p)
    stake = number(stake)
    reasons = []
    if promo.expires_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Timezone required")
    if not promo.kind in ("profit_boost", "sgp_boost", "sgpx", "bonus_bet", "hr_boost", "td_boost"):
        raise ValueError("Unsupported promo")
    if stake <= 0 or stake > promo.max_stake:
        reasons.append("STAKE_LIMIT")
    if book != promo.book:
        reasons.append("WRONG_BOOK")
    if now >= promo.expires_at:
        reasons.append("EXPIRED")
    if price < promo.min_raw_decimal or legs < promo.min_legs:
        reasons.append("RAW_ODDS_OR_LEGS")
    if promo.sports and sport not in promo.sports:
        reasons.append("SPORT_RESTRICTION")
    if promo.markets and not set(markets) <= promo.markets:
        reasons.append("MARKET_RESTRICTION")
    if stacked and not promo.stacking_allowed:
        reasons.append("STACKING")
    if not promo.void_rules_verified:
        reasons.append("VOID_RULES_UNVERIFIED")
    if not base_qualified:
        reasons.append("BASE_WAGER_NOT_QUALIFIED")
    unboosted = roi(p, price)
    effective = profit_boost(price, promo.boost) if promo.kind != "bonus_bet" else None
    boosted = roi(p, effective) if effective else None
    return {
        "status": "PASS" if reasons else "ELIGIBLE_FOR_REVIEW",
        "reasons": reasons,
        "unboosted_roi": unboosted,
        "boosted_roi": boosted,
        "effective_decimal": effective,
        "required_probability": 1 / effective if effective else None,
        "incremental_value": (boosted - unboosted) * stake if boosted is not None else None,
        "bonus_cash_value": bonus_bet_cash_value(p, price, stake)
        if promo.kind == "bonus_bet"
        else None,
    }

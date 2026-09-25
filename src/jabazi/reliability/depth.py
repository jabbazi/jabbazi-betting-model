"""Bob recommends research depth; this function never starts a scan."""

from datetime import datetime


def bob(
    *,
    now: datetime,
    starts,
    slate_size,
    unresolved_news=False,
    volatile_prices=False,
    near_bet=False,
    promo_expiry=None,
    exposed_dollars=0,
):
    if now.tzinfo is None:
        raise ValueError("Aware Central-compatible clock required")
    remaining = [(t - now).total_seconds() / 60 for t in starts if t > now]
    lock = min(remaining) if remaining else None
    reasons = []
    if unresolved_news:
        reasons.append("UNRESOLVED_NEWS")
    if volatile_prices:
        reasons.append("VOLATILE_PRICES")
    if near_bet:
        reasons.append("NEAR_QUALIFICATION")
    if slate_size >= 10:
        reasons.append("LARGE_SLATE")
    if exposed_dollars > 0:
        reasons.append("EXISTING_CASH_EXPOSURE")
    if promo_expiry and 0 < (promo_expiry - now).total_seconds() < 3600:
        reasons.append("PROMO_EXPIRING")
    depth = (
        "HIGH"
        if lock is not None and lock <= 90 and (unresolved_news or near_bet or volatile_prices)
        else "MEDIUM"
        if reasons
        else "LOW"
    )
    return {"depth": depth, "minutes_to_first_lock": lock, "reasons": reasons, "is_scan": False}

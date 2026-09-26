from decimal import Decimal

from .odds import implied_probability


def probability_clv(entry_decimal: Decimal, closing_decimal: Decimal) -> Decimal:
    """Positive means the entry implied probability was cheaper than the close."""
    return implied_probability(closing_decimal) - implied_probability(entry_decimal)


def price_clv(entry_decimal: Decimal, closing_decimal: Decimal) -> Decimal:
    """Return-relative CLV; positive means the bettor captured the better payout."""
    return entry_decimal / closing_decimal - Decimal("1")


def brier_score(observations: list[tuple[Decimal, int]]) -> Decimal:
    if not observations:
        raise ValueError("At least one observation is required")
    if any(
        outcome not in (0, 1) or not Decimal("0") <= p <= Decimal("1")
        for p, outcome in observations
    ):
        raise ValueError("Invalid probability or binary outcome")
    return sum((p - Decimal(outcome)) ** 2 for p, outcome in observations) / len(observations)


def calibration_bucket(probability: Decimal) -> str:
    if not Decimal("0") <= probability <= Decimal("1"):
        raise ValueError("Probability must be between 0 and 1")
    percent = probability * Decimal("100")
    if percent < 55:
        return "50-55" if percent >= 50 else "under-50"
    if percent < 60:
        return "55-60"
    if percent < 65:
        return "60-65"
    if percent < 70:
        return "65-70"
    return "70+"

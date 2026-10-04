"""Exact, side-effect-free odds and expected-value calculations."""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class OddsError(ValueError):
    pass


def _d(value: Decimal | int | str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OddsError("Invalid numeric value") from None
    if not result.is_finite():
        raise OddsError("Odds must be finite")
    return result


def american_to_decimal(american: Decimal | int | str) -> Decimal:
    price = _d(american)
    if price == ZERO or (-HUNDRED < price < HUNDRED):
        raise OddsError("American odds must be <= -100 or >= +100")
    return ONE + (HUNDRED / abs(price) if price < ZERO else price / HUNDRED)


def decimal_to_american(decimal_odds: Decimal | int | str) -> Decimal:
    price = _d(decimal_odds)
    if price <= ONE:
        raise OddsError("Decimal odds must be greater than 1")
    result = -HUNDRED / (price - ONE) if price < Decimal("2") else (price - ONE) * HUNDRED
    return result.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def implied_probability(decimal_odds: Decimal | int | str) -> Decimal:
    price = _d(decimal_odds)
    if price <= ONE:
        raise OddsError("Decimal odds must be greater than 1")
    return ONE / price


def fair_decimal(probability: Decimal | int | str) -> Decimal:
    probability = _d(probability)
    if not ZERO < probability < ONE:
        raise OddsError("Probability must be strictly between 0 and 1")
    return ONE / probability


def proportional_no_vig(implied: list[Decimal]) -> list[Decimal]:
    implied = [_d(p) for p in implied]
    if len(implied) < 2 or any(not ZERO < p < ONE for p in implied):
        raise OddsError("At least two positive implied probabilities are required")
    total = sum(implied, ZERO)
    return [p / total for p in implied]


def expected_value(model_probability: Decimal, decimal_odds: Decimal) -> Decimal:
    model_probability, decimal_odds = _d(model_probability), _d(decimal_odds)
    if not ZERO <= model_probability <= ONE:
        raise OddsError("Probability must be between 0 and 1")
    if decimal_odds <= ONE:
        raise OddsError("Decimal odds must be greater than 1")
    return model_probability * decimal_odds - ONE


def expected_profit(stake: Decimal, model_probability: Decimal, decimal_odds: Decimal) -> Decimal:
    stake = _d(stake)
    if stake < ZERO:
        raise OddsError("Stake cannot be negative")
    return stake * expected_value(model_probability, decimal_odds)


def fractional_kelly(
    model_probability: Decimal, decimal_odds: Decimal, fraction: Decimal
) -> Decimal:
    model_probability, decimal_odds, fraction = (
        _d(model_probability),
        _d(decimal_odds),
        _d(fraction),
    )
    expected_value(model_probability, decimal_odds)
    if not ZERO <= fraction <= ONE:
        raise OddsError("Kelly fraction must be between 0 and 1")
    b = decimal_odds - ONE
    raw = (model_probability * decimal_odds - ONE) / b
    return max(ZERO, raw * fraction)


def max_playable_decimal(model_probability: Decimal, minimum_ev: Decimal) -> Decimal:
    """Minimum decimal payout required to retain the requested EV."""
    model_probability, minimum_ev = _d(model_probability), _d(minimum_ev)
    if not ZERO < model_probability <= ONE or minimum_ev < ZERO:
        raise OddsError("Invalid probability or minimum EV")
    return (ONE + minimum_ev) / model_probability

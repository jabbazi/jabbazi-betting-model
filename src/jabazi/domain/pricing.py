"""Shared, decimal-safe pricing. Edge is a probability difference; ROI is return/stake."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import reduce
from operator import mul
from .odds import american_to_decimal, decimal_to_american

D = Decimal


def number(value):
    try:
        x = D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid number") from None
    if not x.is_finite():
        raise ValueError("Number must be finite")
    return x


def probability(value):
    p = number(value)
    if not 0 <= p <= 1:
        raise ValueError("Probability must be in [0,1]")
    return p


def decimal_price(value):
    d = number(value)
    if d <= 1:
        raise ValueError("Decimal price must exceed 1")
    return d


def american_probability(value):
    price = number(value)
    american_to_decimal(price)  # Validate the American price domain.
    return (-price) / (100 - price) if price < 0 else D(100) / (100 + price)


def fair_american(p):
    p = probability(p)
    if not 0 < p < 1:
        raise ValueError("Finite fair odds require probability in (0,1)")
    return decimal_to_american(1 / p)


def book_hold(prices):
    if len(prices) < 2:
        raise ValueError("Complete market needs at least two prices")
    return sum((1 / decimal_price(d) for d in prices), D(0)) - 1


def no_vig(prices):
    hold = book_hold(prices)
    return tuple((1 / decimal_price(d)) / (1 + hold) for d in prices)


def edge(model_p, market_p):
    return probability(model_p) - probability(market_p)


def haircut(p, absolute_margin):
    """Absolute probability-point haircut; callers must document its estimation."""
    return max(D(0), probability(p) - probability(absolute_margin))


def roi(p, price, push=0):
    p, push = probability(p), probability(push)
    if p + push > 1:
        raise ValueError("Win plus push probability exceeds 1")
    return p * decimal_price(price) + push - 1


def minimum_decimal(p, required_roi=0, push=0):
    p, push = probability(p), probability(push)
    required_roi = number(required_roi)
    if p <= 0 or p + push > 1 or required_roi < 0:
        raise ValueError("Invalid play-to inputs")
    return max(D(1), (1 + required_roi - push) / p)


def dollars(units, unit_size):
    units, unit_size = number(units), number(unit_size)
    if units < 0 or unit_size <= 0:
        raise ValueError("Invalid stake/unit size")
    return units * unit_size


def units(stake, unit_size):
    stake, unit_size = number(stake), number(unit_size)
    if stake < 0 or unit_size <= 0:
        raise ValueError("Invalid stake/unit size")
    return stake / unit_size


def independent_joint(marginals, *, independence_confirmed=False):
    if not independence_confirmed:
        raise ValueError("Dependence model or explicit independence evidence required")
    if not 2 <= len(marginals) <= 4:
        raise ValueError("Support 2–4 legs")
    return reduce(mul, map(probability, marginals), D(1))


def independent_parlay_price(prices):
    if not 2 <= len(prices) <= 4:
        raise ValueError("Support 2–4 legs")
    return reduce(mul, map(decimal_price, prices), D(1))


def frechet_bounds(marginals):
    p = list(map(probability, marginals))
    if not p:
        raise ValueError("Missing marginals")
    return max(D(0), sum(p) - len(p) + 1), min(p)


def scenario_joint(outcomes, weights):
    """Joint probability from shared model scenarios, preserving dependence."""
    if not outcomes or len(outcomes) != len(weights):
        raise ValueError("Scenarios/weights required")
    n = len(outcomes[0])
    if not 2 <= n <= 4 or any(len(row) != n for row in outcomes):
        raise ValueError("Need aligned 2–4-leg scenarios")
    if any(type(x) is not bool for row in outcomes for x in row):
        raise ValueError("Scenario outcomes must be booleans")
    weights = list(map(probability, weights))
    if abs(sum(weights) - 1) > D("1e-12"):
        raise ValueError("Scenario weights must sum to one")
    return sum((w for row, w in zip(outcomes, weights) if all(row)), D(0))


def profit_boost(price, boost, *, profit_cap=None, stake=None):
    price, boost = decimal_price(price), number(boost)
    if boost < 0:
        raise ValueError("Boost cannot be negative")
    extra = (price - 1) * boost
    if profit_cap is not None:
        cap = number(profit_cap)
        amount = number(stake)
        if cap < 0 or amount <= 0:
            raise ValueError("Capped boost requires positive stake")
        extra = min(extra, cap / amount)
    return price + extra


def bonus_bet_cash_value(p, price, face_value):
    value = number(face_value)
    if value < 0:
        raise ValueError("Bonus face value cannot be negative")
    return probability(p) * (decimal_price(price) - 1) * value


def fair_probability_clv(entry_market_p, closing_market_p):
    return probability(closing_market_p) - probability(entry_market_p)


@dataclass(frozen=True)
class Valuation:
    model_probability: D
    adjusted_probability: D
    market_probability: D
    probability_edge: D
    expected_roi: D
    expected_profit: D
    fair_decimal: D | None
    minimum_playable_decimal: D | None


def value(p, market_p, offered, stake=1, uncertainty=0, required_roi=0, push=0):
    p = probability(p)
    push = probability(push)
    if p + push > 1:
        raise ValueError("Win plus push probability exceeds 1")
    market_p = probability(market_p)
    stake = number(stake)
    if stake < 0:
        raise ValueError("Stake cannot be negative")
    adjusted = haircut(p, uncertainty)
    expected = roi(adjusted, offered, push)
    return Valuation(
        p,
        adjusted,
        market_p,
        edge(p, market_p),
        expected,
        stake * expected,
        (1 - probability(push)) / p if p else None,
        minimum_decimal(adjusted, required_roi, push) if adjusted else None,
    )

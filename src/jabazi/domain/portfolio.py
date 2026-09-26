"""Central risk allocation over all reserved and placed positions."""

from dataclasses import dataclass
from decimal import Decimal as D
from .pricing import number, probability, decimal_price


@dataclass(frozen=True)
class Position:
    amount: D
    sport: str
    event: str
    players: frozenset[str] = frozenset()
    theses: frozenset[str] = frozenset()
    parlay: bool = False
    origin: str = "scanner"
    betting_date: str = ""


@dataclass(frozen=True)
class Limits:
    bankroll: D
    unit_size: D = D("30")
    daily: D = D(".20")
    per_bet: D = D(".02")
    thesis: D = D(".04")
    parlays: D = D(".03")
    sport: D = D(".10")
    event: D = D(".05")
    player: D = D(".03")
    kelly_fraction: D = D(".10")
    drawdown_stop: D = D(".20")

    def __post_init__(self):
        for key in self.__dataclass_fields__:
            object.__setattr__(self, key, number(getattr(self, key)))
        if number(self.bankroll) <= 0 or number(self.unit_size) <= 0:
            raise ValueError("Positive bankroll and unit size required")
        for key in (
            "daily",
            "per_bet",
            "thesis",
            "parlays",
            "sport",
            "event",
            "player",
            "kelly_fraction",
            "drawdown_stop",
        ):
            if not 0 < number(getattr(self, key)) <= 1:
                raise ValueError("Risk fractions must be in (0,1]")


@dataclass(frozen=True)
class Allocation:
    dollars: D
    units: D
    reasons: tuple[str, ...]


def allocate(p, price, proposal, positions, limits, *, tier="standard", drawdown=0):
    p = probability(p)
    price = decimal_price(price)
    drawdown = probability(drawdown)
    if drawdown >= limits.drawdown_stop:
        return Allocation(D(0), D(0), ("DRAWDOWN_STOP",))
    tier_units = {
        "speculative": D(".25"),
        "standard": D(".50"),
        "strong": D(".75"),
        "exceptional": D("1"),
    }
    if tier not in tier_units:
        raise ValueError("Unknown evidence tier")
    if not proposal.betting_date:
        raise ValueError("Betting date is required")
    if proposal.parlay and not proposal.theses:
        raise ValueError("Parlays require overlap tags")
    for position in positions:
        if number(position.amount) < 0:
            raise ValueError("Exposure cannot be negative")

    def used(predicate):
        return sum((x.amount for x in positions if predicate(x)), D(0))

    constraints = {
        "daily": limits.bankroll * limits.daily
        - used(lambda x: x.betting_date == proposal.betting_date),
        "per_bet": limits.bankroll * limits.per_bet,
        "sport": limits.bankroll * limits.sport - used(lambda x: x.sport == proposal.sport),
        "event": limits.bankroll * limits.event - used(lambda x: x.event == proposal.event),
    }
    for tag in proposal.theses:
        constraints["thesis:" + tag] = limits.bankroll * limits.thesis - used(
            lambda x: tag in x.theses
        )
    for player in proposal.players:
        constraints["player:" + player] = limits.bankroll * limits.player - used(
            lambda x: player in x.players
        )
    if proposal.parlay:
        constraints["parlays"] = limits.bankroll * limits.parlays - used(lambda x: x.parlay)
    binding = tuple(k for k, v in constraints.items() if v <= 0)
    if binding:
        return Allocation(D(0), D(0), binding)
    kelly = max(D(0), (p * price - 1) / (price - 1)) * limits.kelly_fraction * limits.bankroll
    target = min(tier_units[tier], D(".25") if proposal.parlay else D(1)) * limits.unit_size
    ceiling = min(target, kelly, *constraints.values())
    allowed = [u for u in (D(".25"), D(".50"), D(".75"), D(1)) if u * limits.unit_size <= ceiling]
    if not allowed:
        return Allocation(D(0), D(0), ("BELOW_MINIMUM_TIER",))
    u = max(allowed)
    return Allocation(u * limits.unit_size, u, ())

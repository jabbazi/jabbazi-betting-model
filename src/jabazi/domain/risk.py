from dataclasses import dataclass
from decimal import Decimal

from .odds import fractional_kelly


@dataclass(frozen=True)
class RiskPolicy:
    bankroll: Decimal
    unit_size: Decimal = Decimal("30")
    daily_exposure_limit: Decimal = Decimal("0.20")
    kelly_fraction: Decimal = Decimal("0.10")
    max_bet_fraction: Decimal = Decimal("0.02")
    minimum_edge: Decimal = Decimal("0.02")
    stale_after_seconds: Decimal = Decimal("120")

    def __post_init__(self) -> None:
        if self.bankroll <= 0 or self.unit_size <= 0:
            raise ValueError("Bankroll and unit size must be positive")
        if not Decimal("0") < self.daily_exposure_limit <= Decimal("1"):
            raise ValueError("Daily exposure limit must be in (0, 1]")

    def stake(self, probability: Decimal, odds: Decimal, current_exposure: Decimal) -> Decimal:
        capacity = self.bankroll * self.daily_exposure_limit - current_exposure
        if capacity <= 0:
            return Decimal("0")
        kelly_amount = self.bankroll * fractional_kelly(probability, odds, self.kelly_fraction)
        hard_per_bet = self.bankroll * self.max_bet_fraction
        raw = min(capacity, kelly_amount, hard_per_bet)
        # Legacy entry points cannot silently size above a standard 0.5u.
        eligible = [
            u * self.unit_size
            for u in (Decimal(".25"), Decimal(".50"))
            if u * self.unit_size <= raw
        ]
        return max(eligible, default=Decimal(0))

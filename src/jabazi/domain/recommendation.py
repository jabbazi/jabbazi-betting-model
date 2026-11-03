from dataclasses import dataclass, field
from decimal import Decimal

from .models import Decision
from .odds import expected_value, max_playable_decimal
from .risk import RiskPolicy
from .shopping import PriceCard


@dataclass(frozen=True)
class ActionCard:
    price: PriceCard
    decision: Decision
    model_probability: Decimal | None
    estimated_ev: Decimal | None
    stake: Decimal
    maximum_playable_decimal: Decimal | None
    reason: str
    probability_edge: Decimal | None = None
    expected_roi: Decimal | None = None
    model_version: str | None = None
    reservation_id: str | None = None
    uncertainty: Decimal | None = None
    reliability: dict = field(default_factory=dict)


def recommend_price(
    card: PriceCard,
    policy: RiskPolicy,
    model_probability: Decimal | None = None,
    uncertainty: Decimal = Decimal("0"),
    current_exposure: Decimal = Decimal("0"),
    model_validated: bool = False,
    jurisdiction: str = "LA",
) -> ActionCard:
    if card.in_play:
        return ActionCard(
            card,
            Decision.WAIT,
            model_probability,
            None,
            Decimal("0"),
            None,
            "Event is in-play; validated live model and latency controls are required",
        )
    if card.stale:
        return ActionCard(
            card,
            Decision.WAIT,
            model_probability,
            None,
            Decimal("0"),
            None,
            "Price is stale; refresh before acting",
        )
    from .health import allowed_market

    if not allowed_market(card.sport, card.market, jurisdiction):
        return ActionCard(
            card,
            Decision.PASS,
            model_probability,
            None,
            Decimal("0"),
            None,
            "Market is excluded by the configured jurisdiction policy",
        )
    if model_probability is None:
        decision = Decision.WATCH if card.market_relative_ev > 0 else Decision.PASS
        return ActionCard(
            card,
            decision,
            None,
            None,
            Decimal("0"),
            None,
            "Price-shopping signal only; no validated independent model probability",
        )
    if not model_validated:
        return ActionCard(
            card,
            Decision.WATCH,
            model_probability,
            None,
            Decimal("0"),
            None,
            "Model estimate exists but has not passed production validation gates",
        )
    if not card.executable:
        return ActionCard(
            card,
            Decision.WATCH,
            model_probability,
            None,
            Decimal("0"),
            None,
            "Insufficient fresh, complete, agreeing sportsbook evidence",
        )
    if not Decimal("0") <= uncertainty <= Decimal("1"):
        raise ValueError("Uncertainty must be between 0 and 1")
    adjusted = model_probability * (Decimal("1") - uncertainty)
    if adjusted <= 0:
        return ActionCard(
            card,
            Decision.PASS,
            model_probability,
            Decimal("-1"),
            Decimal("0"),
            None,
            "Uncertainty leaves no positive probability to price",
        )
    ev = expected_value(adjusted, card.best_decimal)
    threshold = policy.minimum_edge + (current_exposure / policy.bankroll) / Decimal("5")
    playable = max_playable_decimal(adjusted, threshold)
    if ev < threshold:
        return ActionCard(
            card,
            Decision.PASS,
            model_probability,
            ev,
            Decimal("0"),
            playable,
            "Uncertainty-adjusted EV is below the portfolio threshold",
        )
    stake = policy.stake(adjusted, card.best_decimal, current_exposure)
    if stake <= 0:
        return ActionCard(
            card,
            Decision.PASS,
            model_probability,
            ev,
            stake,
            playable,
            "Risk limits leave no available capacity",
        )
    return ActionCard(
        card,
        Decision.BET_NOW,
        model_probability,
        ev,
        stake,
        playable,
        "Independent model probability clears price and risk thresholds",
        probability_edge=model_probability - card.consensus_probability,
        expected_roi=ev,
    )

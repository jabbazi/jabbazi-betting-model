from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from .shopping import PriceCard


@dataclass(frozen=True)
class ArbitrageLeg:
    selection: str
    participant: str | None
    line: Decimal | None
    sportsbook: str
    decimal_odds: Decimal
    stake: Decimal


@dataclass(frozen=True)
class ArbitrageOpportunity:
    event: str
    market: str
    total_stake: Decimal
    guaranteed_return: Decimal
    guaranteed_profit: Decimal
    roi: Decimal
    legs: tuple[ArbitrageLeg, ...]


def _instance(card: PriceCard) -> tuple:
    line = card.line
    if card.market in {"spreads", "alternate_spreads"} and line is not None:
        line = abs(line)
    return card.event_id, card.market, card.participant, line


def find_arbitrage(cards: list[PriceCard], total_capital: Decimal) -> list[ArbitrageOpportunity]:
    if total_capital <= 0:
        raise ValueError("Total capital must be positive")
    groups: dict[tuple, list[PriceCard]] = defaultdict(list)
    for card in cards:
        if not card.stale and not card.in_play:
            groups[_instance(card)].append(card)
    opportunities: list[ArbitrageOpportunity] = []
    for group in groups.values():
        # A valid market needs distinct exhaustive outcomes. Duplicate cards are collapsed.
        outcomes: dict[tuple[str, Decimal | None], PriceCard] = {}
        for card in group:
            outcome_key = (card.selection, card.line)
            prior = outcomes.get(outcome_key)
            if prior is None or card.best_decimal > prior.best_decimal:
                outcomes[outcome_key] = card
        if len(outcomes) < 2:
            continue
        market = group[0].market
        if market == "outrights":
            continue
        if len({card.best_book for card in outcomes.values()}) < 2:
            continue
        if "spreads" in market:
            lines = {card.line for card in outcomes.values() if card.line is not None}
            if len(outcomes) != 2 or len(lines) != 2 or sum(lines, Decimal("0")) != 0:
                continue
        if "totals" in market or market.startswith(("player_", "pitcher_", "batter_")):
            sides = {card.selection.lower() for card in outcomes.values()}
            if not ({"over", "under"}.issubset(sides) or {"yes", "no"}.issubset(sides)):
                continue
        inverse_sum = sum(
            (Decimal("1") / card.best_decimal for card in outcomes.values()), Decimal("0")
        )
        if inverse_sum >= Decimal("1"):
            continue
        guaranteed_return = total_capital / inverse_sum
        legs = []
        for card in outcomes.values():
            stake = (guaranteed_return / card.best_decimal).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            legs.append(
                ArbitrageLeg(
                    card.selection,
                    card.participant,
                    card.line,
                    card.best_book,
                    card.best_decimal,
                    stake,
                )
            )
        # Penny rounding leaves a small unallocated remainder; put it on the lowest-return leg.
        allocated = sum((leg.stake for leg in legs), Decimal("0"))
        remainder = total_capital - allocated
        if remainder:
            index = min(range(len(legs)), key=lambda i: legs[i].stake * legs[i].decimal_odds)
            leg = legs[index]
            legs[index] = ArbitrageLeg(
                leg.selection,
                leg.participant,
                leg.line,
                leg.sportsbook,
                leg.decimal_odds,
                leg.stake + remainder,
            )
        actual_return = min(leg.stake * leg.decimal_odds for leg in legs)
        profit = actual_return - total_capital
        opportunities.append(
            ArbitrageOpportunity(
                group[0].event,
                group[0].market,
                total_capital,
                actual_return,
                profit,
                profit / total_capital,
                tuple(legs),
            )
        )
    return sorted(opportunities, key=lambda opportunity: opportunity.roi, reverse=True)

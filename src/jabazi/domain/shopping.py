"""Universal line shopping for teams, props, totals, and alternate rungs."""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median

from .models import Quote, DataQuality
from .odds import implied_probability

BOOK_DISPLAY = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "williamhill_us": "Caesars",
    "caesars": "Caesars",
    "betmgm": "BetMGM",
    "betrivers": "BetRivers",
    "thescorebet": "theScore Bet",
    "espnbet": "theScore Bet",
}


@dataclass(frozen=True)
class PriceCard:
    sport: str
    event_id: str
    event: str
    market: str
    participant: str | None
    selection: str
    line: Decimal | None
    book_prices: dict[str, Decimal]
    best_book: str
    best_decimal: Decimal
    consensus_probability: Decimal
    market_relative_ev: Decimal
    sportsbook_disagreement: Decimal
    stale: bool
    in_play: bool
    quote_ids: tuple[str, ...]
    observed_at: datetime = datetime.min.replace(tzinfo=timezone.utc)
    source_timestamp: datetime = datetime.min.replace(tzinfo=timezone.utc)
    starts_at: datetime | None = None
    book_holds: dict[str, Decimal] = field(default_factory=dict)
    book_no_vig: dict[str, Decimal] = field(default_factory=dict)
    executable: bool = False


def _parts(quote: Quote) -> tuple[str | None, str]:
    if "|" in quote.selection_key:
        participant, side = quote.selection_key.rsplit("|", 1)
        return participant, side
    return None, quote.selection_key


def _instance_key(quote: Quote) -> tuple[str, str, str | None, Decimal | None]:
    participant, _ = _parts(quote)
    line = quote.line
    if "spreads" in quote.market_key and line is not None:
        line = abs(line)
    return quote.event_id, quote.market_key, participant, line


def _complete_instance(market: str, quotes: list[Quote]) -> bool:
    """Reject pseudo-pairs such as both baseball teams at -8.5 alternate spread."""
    if len(quotes) < 2:
        return False
    if "spreads" in market:
        if len(quotes) != 2 or len({q.selection_key for q in quotes}) != 2:
            return False
        lines = {quote.line for quote in quotes if quote.line is not None}
        return (len(lines) == 2 and sum(lines, Decimal("0")) == Decimal("0")) or (
            lines == {Decimal(0)} and len({q.selection_key for q in quotes}) == 2
        )
    if "totals" in market or market.startswith(("player_", "pitcher_", "batter_")):
        sides = {_parts(quote)[1].lower() for quote in quotes}
        return len(quotes) == 2 and sides in ({"over", "under"}, {"yes", "no"})
    return True


def build_price_cards(
    quotes: tuple[Quote, ...],
    stale_after_seconds: Decimal = Decimal("120"),
    now: datetime | None = None,
) -> list[PriceCard]:
    """Price identical selections and de-vig only complete same-book market instances."""
    now = now or datetime.now(timezone.utc)
    instances: dict[tuple, list[Quote]] = defaultdict(list)
    for quote in quotes:
        if quote.source_timestamp.tzinfo is None or quote.observed_at.tzinfo is None:
            continue
        if not quote.decimal_odds.is_finite() or quote.decimal_odds <= 1:
            continue
        if not (Decimal(0) <= quote.age_seconds(now) <= stale_after_seconds):
            continue
        observed_age = Decimal(str((now - quote.observed_at).total_seconds()))
        if not Decimal(0) <= observed_age <= stale_after_seconds:
            continue
        if quote.quality not in {DataQuality.REALTIME, DataQuality.DELAYED}:
            continue
        instances[_instance_key(quote)].append(quote)

    cards: list[PriceCard] = []
    for (_event_id, _market, participant, _instance_line), instance_quotes in instances.items():
        first_card = len(cards)
        by_book: dict[str, list[Quote]] = defaultdict(list)
        for quote in instance_quotes:
            by_book[quote.sportsbook].append(quote)
        # One latest quote per side/rung. Retransmitted snapshots cannot add vig.
        for book, values in by_book.items():
            latest = {}
            for quote in sorted(values, key=lambda q: q.source_timestamp):
                latest[(quote.selection_key, quote.line)] = quote
            by_book[book] = list(latest.values())
        selection_keys = {(quote.selection_key, quote.line) for quote in instance_quotes}
        for selection_key, selection_line in selection_keys:
            matching = [
                q
                for q in instance_quotes
                if q.selection_key == selection_key and q.line == selection_line
            ]
            prices: dict[str, Decimal] = {}
            fair_probabilities: list[Decimal] = []
            holds, by_book_fair = {}, {}
            for book, book_quotes in by_book.items():
                target = next(
                    (
                        q
                        for q in book_quotes
                        if q.selection_key == selection_key and q.line == selection_line
                    ),
                    None,
                )
                if target is None or not _complete_instance(_market, book_quotes):
                    continue
                if _market == "outrights":
                    continue  # Outcome completeness requires a separate declared universe.
                if _market.startswith("h2h"):
                    expected = 3 if target.sport and target.sport.startswith("soccer") else 2
                    if len({q.selection_key for q in book_quotes}) != expected:
                        continue
                # Providers occasionally emit suspended/sentinel prices at or below 1.
                # Quarantine the whole same-book instance instead of aborting the feed.
                if target.decimal_odds <= Decimal("1") or any(
                    q.decimal_odds <= Decimal("1") for q in book_quotes
                ):
                    continue
                implied = [implied_probability(q.decimal_odds) for q in book_quotes]
                total = sum(implied, Decimal("0"))
                fair_probabilities.append(implied_probability(target.decimal_odds) / total)
                prices[BOOK_DISPLAY.get(book, book)] = target.decimal_odds
                display = BOOK_DISPLAY.get(book, book)
                holds[display] = total - 1
                by_book_fair[display] = fair_probabilities[-1]
            if not prices or not fair_probabilities:
                continue
            if len(by_book_fair) >= 3:
                center = Decimal(str(median(by_book_fair.values())))
                mad = Decimal(str(median([abs(p - center) for p in by_book_fair.values()])))
                cutoff = max(Decimal(".10"), 4 * mad)
                accepted = {book for book, p in by_book_fair.items() if abs(p - center) <= cutoff}
                prices = {b: p for b, p in prices.items() if b in accepted}
                holds = {b: p for b, p in holds.items() if b in accepted}
                by_book_fair = {b: p for b, p in by_book_fair.items() if b in accepted}
            fair_probabilities = list(by_book_fair.values())
            best_book, best_price = max(prices.items(), key=lambda item: item[1])
            consensus = Decimal(str(median(fair_probabilities)))
            valid_matching = [q for q in matching if q.decimal_odds > Decimal("1")]
            raw_implied = [implied_probability(q.decimal_odds) for q in valid_matching]
            disagreement = (
                max(raw_implied) - min(raw_implied) if len(raw_implied) > 1 else Decimal("0")
            )
            chosen = max(
                (
                    q
                    for q in valid_matching
                    if BOOK_DISPLAY.get(q.sportsbook, q.sportsbook) == best_book
                ),
                key=lambda q: q.source_timestamp,
            )
            _, side = _parts(chosen)
            in_play = chosen.commence_time is not None and chosen.commence_time <= now
            cards.append(
                PriceCard(
                    sport=chosen.sport or "unknown",
                    event_id=chosen.event_id,
                    event=chosen.event_name or chosen.event_id,
                    market=chosen.market_key,
                    participant=participant,
                    selection=side,
                    line=chosen.line,
                    book_prices=prices,
                    best_book=best_book,
                    best_decimal=best_price,
                    consensus_probability=consensus,
                    market_relative_ev=consensus * best_price - Decimal("1"),
                    sportsbook_disagreement=disagreement,
                    stale=chosen.age_seconds(now) > stale_after_seconds,
                    in_play=in_play,
                    quote_ids=tuple(sorted(q.provider_quote_id for q in matching)),
                    observed_at=chosen.observed_at,
                    source_timestamp=chosen.source_timestamp,
                    starts_at=chosen.commence_time,
                    book_holds=holds,
                    book_no_vig=by_book_fair,
                    executable=len(by_book_fair) >= 2
                    and max(fair_probabilities) - min(fair_probabilities) <= Decimal(".10"),
                )
            )
        # Componentwise medians do not necessarily sum to one for three-way markets.
        complete_cards = cards[first_card:]
        mass = sum((card.consensus_probability for card in complete_cards), Decimal(0))
        if mass:
            for index in range(first_card, len(cards)):
                probability = cards[index].consensus_probability / mass
                cards[index] = replace(
                    cards[index],
                    consensus_probability=probability,
                    market_relative_ev=probability * cards[index].best_decimal - 1,
                )
    return sorted(cards, key=lambda card: card.market_relative_ev, reverse=True)

from collections import defaultdict
from decimal import Decimal

from .models import Quote
from .odds import implied_probability, proportional_no_vig


def best_quote(quotes: tuple[Quote, ...]) -> Quote:
    if not quotes:
        raise ValueError("At least one quote is required")
    return max(quotes, key=lambda quote: quote.decimal_odds)


def consensus_probability(
    selection_quotes: tuple[Quote, ...], opposing_quotes: tuple[Quote, ...]
) -> Decimal:
    """Median-like cross-book consensus using per-book proportional de-vigging."""
    by_book: dict[str, dict[str, list[Quote]]] = defaultdict(lambda: defaultdict(list))
    for quote in selection_quotes:
        by_book[quote.sportsbook]["target"].append(quote)
    for quote in opposing_quotes:
        by_book[quote.sportsbook]["other"].append(quote)
    probabilities: list[Decimal] = []
    for sides in by_book.values():
        if not sides["target"] or not sides["other"]:
            continue
        target = max(sides["target"], key=lambda q: q.decimal_odds)
        others = [max(sides["other"], key=lambda q: q.decimal_odds)]
        no_vig = proportional_no_vig(
            [implied_probability(target.decimal_odds)]
            + [implied_probability(quote.decimal_odds) for quote in others]
        )
        probabilities.append(no_vig[0])
    if not probabilities:
        raise ValueError("No sportsbook has a complete market")
    probabilities.sort()
    midpoint = len(probabilities) // 2
    if len(probabilities) % 2:
        return probabilities[midpoint]
    return (probabilities[midpoint - 1] + probabilities[midpoint]) / Decimal("2")

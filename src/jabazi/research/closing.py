"""Closing proxy from archived, complete pregame markets; never a postgame price."""

from datetime import timedelta
from decimal import Decimal as D
from jabazi.domain.shopping import build_price_cards


def closing_proxy(
    quotes, *, starts_at, now, event_id, market, selection, line=None, participant=None
):
    if starts_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Aware timestamps required")
    if now < starts_at:
        return {"status": "WAIT_FOR_CLOSE"}
    before = starts_at - timedelta(microseconds=1)
    event_quotes = tuple(q for q in quotes if q.event_id == event_id)
    cards = build_price_cards(event_quotes, stale_after_seconds=D(120), now=before)
    matching = [
        c
        for c in cards
        if c.market == market
        and c.selection == selection
        and c.line == line
        and c.participant == participant
        and c.executable
    ]
    if not matching:
        return {
            "status": "UNAVAILABLE",
            "reason": "No complete multi-book snapshot within two minutes before start",
        }
    card = matching[0]
    return {
        "status": "CLOSING_PROXY",
        "probability": card.consensus_probability,
        "fair_decimal": 1 / card.consensus_probability,
        "line": card.line,
        "source_books": list(card.book_no_vig),
        "quote_ids": card.quote_ids,
        "source_timestamp": card.source_timestamp,
        "starts_at": starts_at,
        "note": "Latest eligible archived consensus; not a certified final sportsbook close",
    }

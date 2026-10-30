"""Fail-closed 2/3/4-leg boost structure enumeration.

These combinations have NO approved joint probabilities or executable combined
bookmaker prices. They are possible research structures, never bets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations


@dataclass(frozen=True)
class BoostLeg:
    identifier: str
    sport: str
    event_id: str
    player_id: str
    market: str
    side: str
    book: str
    quoted_at: datetime
    starts_at: datetime


@dataclass(frozen=True)
class BoostTicketTerms:
    sport: str
    book: str
    min_legs: int
    max_legs: int
    event_ids: frozenset[str]
    markets: frozenset[str]


def enumerate_research_tickets(
    legs: list[BoostLeg], terms: BoostTicketTerms, *,
    observed_at: datetime, feed_coverage: str,
    terms_verified: bool, promotion_active: bool,
    max_quote_age: timedelta = timedelta(minutes=5),
    maximum_combinations: int = 2500,
) -> tuple[tuple[str, ...], ...]:
    """Enumerate eligible structures, requiring separate joint and quote checks.

    Returns no ticket if terms, coverage or promo eligibility are unverified.
    Inconsistent/oversized sets fail closed; do not partially enumerate a cap.
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Observation time must be timezone-aware")
    if not 2 <= terms.min_legs <= terms.max_legs <= 4:
        raise ValueError("Promotion must specify permitted 2-4 leg limits")
    if max_quote_age <= timedelta(0) or maximum_combinations < 1:
        raise ValueError("Invalid freshness or enumeration cap")
    if feed_coverage != "FULL" or not terms_verified or not promotion_active:
        return ()
    eligible = []
    seen_ids = set()
    for leg in legs:
        if (not leg.identifier or not leg.event_id or not leg.player_id
                or not leg.market or not leg.side or not leg.book):
            continue
        if leg.identifier in seen_ids:
            # Duplicate offer identity makes quote reconciliation ambiguous.
            raise ValueError("Duplicate leg quote identity")
        seen_ids.add(leg.identifier)
        if leg.sport != terms.sport or leg.book != terms.book:
            continue
        if terms.event_ids and leg.event_id not in terms.event_ids:
            continue
        if terms.markets and leg.market not in terms.markets:
            continue
        if leg.quoted_at.tzinfo is None or leg.starts_at.tzinfo is None:
            continue
        age = observed_at - leg.quoted_at
        if not timedelta(0) <= age <= max_quote_age:
            continue
        if leg.starts_at <= observed_at:
            continue
        eligible.append(leg)

    # Stable enumeration for reproducible downstream quote requests.
    eligible.sort(key=lambda x: x.identifier)
    results = []
    for leg_count in range(terms.min_legs, terms.max_legs + 1):
        for selected in combinations(eligible, leg_count):
            # Avoid incompatible selections on the same player/stat market.
            identities = [(x.event_id, x.player_id, x.market) for x in selected]
            if len(set(identities)) != len(selected):
                continue
            # Distinct quote identifiers alone do not imply price availability.
            results.append(tuple(x.identifier for x in selected))
            if len(results) > maximum_combinations:
                raise ValueError("Combination cap exceeded; narrow boost scope")
    return tuple(results)

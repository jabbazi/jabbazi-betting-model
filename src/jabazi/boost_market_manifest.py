"""Published priority prop categories for the V6 NBA/NFL/NHL research workflow.

These are SOURCE-DOCUMENTED provider identifiers, not a promise every
market, game, sportsbook or player has an offer. NFL prop_type is open-ended.
No calculated model probability or bookmaker executable price is inferred.
"""
from __future__ import annotations

from typing import Mapping

# Sources: https://docs.balldontlie.io/ (NBA player props),
# https://nfl.balldontlie.io/ (NFL player props),
# https://nhl.balldontlie.io/ (NHL player props).
PRIORITY_MARKETS = {
    "NBA": (
        "points", "rebounds", "assists", "threes",
        "points_rebounds", "points_assists", "rebounds_assists",
        "points_rebounds_assists",
    ),
    "NFL": (
        "passing_yards", "passing_tds", "rushing_yards",
        "rushing_attempts", "receiving_yards", "receptions",
        "anytime_td", "first_td", "rushing_receiving_yards",
    ),
    "NHL": (
        "goals", "assists", "points", "shots_on_goal", "saves",
        "anytime_goal", "first_goal",
    ),
}


def audit_priority_market_presence(sport: str, observed: Mapping, *,
                                   eligible_games: int) -> dict:
    """Compute observational coverage without conflating absent markets with errors.

    An absent market on an observed game may mean unsupported, suspended,
    no eligible players, or a different sportsbook's current offering.
    This function NEVER certifies full model/prop/feed coverage.
    """
    if sport not in PRIORITY_MARKETS:
        raise ValueError("Unsupported priority-market sport")
    if type(eligible_games) is not int or eligible_games < 0:
        raise ValueError("Invalid eligible game count")
    if not isinstance(observed, Mapping):
        raise ValueError("Observed-market data required")
    if not isinstance(observed.get("markets"), Mapping):
        raise ValueError("Sanitized observed-market map required")
    seen = observed["markets"]
    categories = []
    for market in PRIORITY_MARKETS[sport]:
        entry = seen.get(market, {})
        count = entry.get("games_with_market", 0) if isinstance(entry, Mapping) else 0
        rows = entry.get("accepted_quote_rows", 0) if isinstance(entry, Mapping) else 0
        if (type(count) is not int or type(rows) is not int
                or count < 0 or rows < 0 or count > eligible_games):
            raise ValueError("Invalid observed-market game count")
        categories.append({
            "prop_type": market,
            "games_with_any_accepted_quote": count,
            "games_without_observed_quote": eligible_games - count,
            "accepted_quote_rows": rows,
            "observation": "OBSERVED" if count else "NOT_OBSERVED",
        })
    return {
        "sport": sport,
        "eligible_games": eligible_games,
        "priority_market_count": len(categories),
        "priority_markets_observed": sum(bool(row["games_with_any_accepted_quote"]) for row in categories),
        "categories": categories,
        "status": "OBSERVATIONAL_RESEARCH_ONLY",
        "source_defined_market_universe_complete": False,
        "every_player_and_book_verified": False,
        "executable_parlay_quote_verified": False,
    }

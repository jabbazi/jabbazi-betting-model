"""De-identified market breadth audit of already validated live prop offers.

Reads only accepted rows from collect_boost_odds. This measures which
sportbook-prop categories were observed, NOT whether all markets or players
are available. It makes no network calls and cannot authorize a wager.
"""
from __future__ import annotations

from collections import defaultdict
import re

# Report only normalized market labels, never arbitrary vendor strings.
_SAFE_MARKET = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_MARKETS = 128


def summarize_prop_markets(rows):
    """Aggregate per-market observed games, bookmakers and side support.

    Retain no player IDs, vendor names, raw prices, links or game IDs in the
    returned JSON. A malformed or unexpected row fails closed as unclassified;
    no untrusted string is copied to the output.
    """
    markets = defaultdict(lambda: {
        "quotes": 0, "over_under_quotes": 0, "milestone_quotes": 0,
        "two_sided_quotes": 0, "games": set(), "books": set(),
    })
    unclassified = 0
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("raw"), dict):
            unclassified += 1
            continue
        raw = item["raw"]
        label = raw.get("prop_type")
        vendor = raw.get("vendor")
        game_id = item.get("game_id")
        market = raw.get("market")
        if (not isinstance(label, str) or not _SAFE_MARKET.fullmatch(label)
                or not isinstance(vendor, str) or not vendor.strip()
                or not isinstance(game_id, int) or isinstance(game_id, bool)
                or not isinstance(market, dict)):
            unclassified += 1
            continue
        if label not in markets and len(markets) >= _MAX_MARKETS:
            unclassified += 1
            continue
        bucket = markets[label]
        bucket["quotes"] += 1
        bucket["games"].add(game_id)
        bucket["books"].add(vendor.lower().strip())
        if market.get("type") == "over_under":
            bucket["over_under_quotes"] += 1
            if (type(market.get("over_odds")) is int
                    and type(market.get("under_odds")) is int):
                bucket["two_sided_quotes"] += 1
        elif market.get("type") == "milestone":
            bucket["milestone_quotes"] += 1
        else:
            unclassified += 1

    return {
        "market_types_seen": len(markets),
        "unclassified_rows": unclassified,
        "classification_complete": unclassified == 0,
        "markets": {
            label: {
                "accepted_quote_rows": value["quotes"],
                "games_with_market": len(value["games"]),
                "distinct_bookmakers": len(value["books"]),
                "over_under_rows": value["over_under_quotes"],
                "two_sided_rows": value["two_sided_quotes"],
                "milestone_rows": value["milestone_quotes"],
            }
            for label, value in sorted(markets.items())
        },
        "status": "OBSERVED_ONLY",
        "player_hit_probabilities_verified": False,
        "all_eligible_markets_verified": False,
        "executable_bookmaker_quotes_verified": False,
    }

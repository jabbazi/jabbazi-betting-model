"""Sport-scoped boost request and paid probability row validation.

This module deliberately does not fetch feeds or certify model probabilities.
The ordinary AutomaticScanner is not modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

SPORTS = {"NBA": "basketball_nba", "NFL": "americanfootball_nfl", "NHL": "icehockey_nhl"}


@dataclass(frozen=True)
class BoostScope:
    sport: str
    event_ids: frozenset[str] = frozenset()
    markets: frozenset[str] = frozenset()

    def __post_init__(self):
        if self.sport not in SPORTS.values():
            raise ValueError("Boost must specify exactly one supported sport")
        if any(not item for item in self.event_ids | self.markets):
            raise ValueError("Blank event or market identifier")


def scope_from_text(text: str, *, event_ids: Iterable[str] = (),
                    markets: Iterable[str] = ()) -> BoostScope:
    """Fail closed when a promotion's sport is missing or ambiguous."""
    import re
    matches = [code for label, code in SPORTS.items()
               if re.search(r"\b" + label + r"\b", text.upper())]
    if len(matches) != 1:
        raise ValueError("BOOST_SPORT_MISSING_OR_AMBIGUOUS")
    return BoostScope(matches[0], frozenset(event_ids), frozenset(markets))


def eligible_rows(scope: BoostScope, rows: Iterable[Mapping],
                  *, observed_after: datetime) -> tuple[list[dict], dict]:
    """Filter only eligible sport/event/market rows; audit rejects and duplicates.

    Requires aware timestamps and a stable player/market/line/side identity.
    Missing fields are rejected, never filled with fabricated values.
    """
    if observed_after.tzinfo is None or observed_after.utcoffset() is None:
        raise ValueError("observed_after must be timezone aware")
    accepted: dict[tuple, dict] = {}
    counts = {"received": 0, "wrong_sport": 0, "out_of_scope": 0,
              "invalid": 0, "stale": 0, "duplicates": 0}
    for raw in rows:
        counts["received"] += 1
        if not isinstance(raw, Mapping):
            counts["invalid"] += 1
            continue
        if raw.get("sport") != scope.sport:
            counts["wrong_sport"] += 1
            continue
        if (scope.event_ids and raw.get("event_id") not in scope.event_ids) or (
            scope.markets and raw.get("market") not in scope.markets
        ):
            counts["out_of_scope"] += 1
            continue
        try:
            key = tuple(raw[k] for k in ("event_id", "player_id", "market",
                                         "line", "side", "provider"))
            if any(v is None or v == "" for v in key):
                raise ValueError("Missing identity")
            p = float(raw["probability"])
            if not 0 <= p <= 1:
                raise ValueError("Invalid probability")
            from math import isfinite
            if not isfinite(p):
                raise ValueError("Nonfinite probability")
            ts = datetime.fromisoformat(str(raw["observed_at"]).replace("Z", "+00:00"))
            if ts.tzinfo is None or ts.utcoffset() is None:
                raise ValueError("Naive timestamp")
        except (KeyError, TypeError, ValueError, OverflowError):
            counts["invalid"] += 1
            continue
        if ts < observed_after or ts > datetime.now(timezone.utc):
            counts["stale"] += 1
            continue
        if key in accepted:
            counts["duplicates"] += 1
            if ts <= datetime.fromisoformat(accepted[key]["observed_at"].replace("Z", "+00:00")):
                continue
        accepted[key] = dict(raw)
    counts["accepted"] = len(accepted)
    # This is only row-filter coverage, not proof of complete provider pagination.
    counts["coverage"] = "UNVERIFIED_PROVIDER_COMPLETENESS"
    return list(accepted.values()), counts

"""Read-only sport-isolated BALLDONTLIE odds collection and integrity audit.

Vendor player props are *prices*, not calibrated player hit probabilities.
An HTTP 200 and completed pagination do not establish actionable coverage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from jabazi.boost_offer_integrity import inspect_prop_offer

from jabazi.boost_scope import BoostScope
from jabazi.providers.balldontlie import BallDontLieError

VENDOR_SPORT = {
    "basketball_nba": "nba",
    "americanfootball_nfl": "nfl",
    "icehockey_nhl": "nhl",
}


@dataclass(frozen=True)
class BoostFeedReport:
    sport: str
    games_requested: int
    games_succeeded: int
    odds_rows: int
    pages: int
    coverage: str
    errors: tuple[str, ...]
    rows: tuple[dict, ...]
    raw_odds_rows: int = 0
    duplicate_rows: int = 0
    invalid_rows: int = 0
    mismatched_game_rows: int = 0
    game_row_counts: tuple[tuple[int, int], ...] = ()
    stale_rows: int = 0
    out_of_scope_rows: int = 0


def _valid_identifier(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def collect_boost_odds(provider, scope: BoostScope, *, game_ids: Iterable[int],
                       max_pages_per_game: int = 100) -> BoostFeedReport:
    """Collect exact-game provider prices with auditable schema and deduplication.

    Missing/foreign IDs are rejected. Duplicates are counted and not silently
    interpreted as additional markets. Any integrity failure downgrades coverage.
    No odds price is ever reinterpreted as a hit probability.
    """
    sport = VENDOR_SPORT[scope.sport]
    ids = list(game_ids)
    if not ids or len(ids) > 100 or any(not _valid_identifier(gid) for gid in ids):
        raise ValueError("Provide 1-100 valid game IDs")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate game IDs")
    if scope.event_ids and set(map(str, ids)) != scope.event_ids:
        raise ValueError("Game IDs do not match promotion scope")
    rows, errors, pages, succeeded = [], [], 0, 0
    raw_count = duplicate_count = invalid_count = foreign_count = 0
    stale_count = out_of_scope_count = 0
    seen = set()
    per_game = []
    for gid in ids:
        count = 0
        try:
            response = provider.fetch_all_pages(
                sport, "props", [("game_id", gid)],
                max_pages=max_pages_per_game,
            )
            if not response.get("complete"):
                raise BallDontLieError("INCOMPLETE_PAGINATION")
            succeeded += 1
            pages += response["pages"]
            for row in response["data"]:
                raw_count += 1
                if scope.markets and isinstance(row, dict) and row.get("prop_type") not in scope.markets:
                    out_of_scope_count += 1
                    continue
                identity, issue = inspect_prop_offer(
                    row, gid, observed_at=datetime.now(UTC),
                )
                if issue == "FOREIGN_GAME_ID":
                    foreign_count += 1
                    continue
                if issue == "STALE_OR_FUTURE_VENDOR_QUOTE":
                    stale_count += 1
                    continue
                if issue is not None:
                    invalid_count += 1
                    continue
                if identity in seen:
                    duplicate_count += 1
                    continue
                seen.add(identity)
                rows.append({"sport": scope.sport, "game_id": gid,
                             "vendor": "BALLDONTLIE", "raw": row})
                count += 1
        except BallDontLieError as exc:
            errors.append(f"game:{gid}:{exc}")
            # Stop on entitlement failures and exhausted budget to avoid
            # repeated rejected calls or automatic retrials.
            if str(exc) in {"HTTP_401", "HTTP_403", "HTTP_429",
                            "REQUEST_BUDGET_EXHAUSTED"}:
                per_game.append((gid, count))
                break
        per_game.append((gid, count))
    if invalid_count:
        errors.append("INVALID_PROP_IDENTITIES")
    if foreign_count:
        errors.append("FOREIGN_GAME_PROP_IDENTITIES")
    if duplicate_count:
        errors.append("DUPLICATE_PROP_IDENTITIES")
    if stale_count:
        errors.append("STALE_PROP_QUOTES")
    return BoostFeedReport(
        sport=scope.sport, games_requested=len(ids),
        games_succeeded=succeeded, odds_rows=len(rows), pages=pages,
        coverage="FULL" if succeeded == len(ids) and not errors else
                 "FAILED" if succeeded == 0 else "PARTIAL",
        errors=tuple(errors), rows=tuple(rows),
        raw_odds_rows=raw_count, duplicate_rows=duplicate_count,
        invalid_rows=invalid_count, mismatched_game_rows=foreign_count,
        game_row_counts=tuple(per_game),
        stale_rows=stale_count, out_of_scope_rows=out_of_scope_count,
    )

"""Read-only, sport-isolated BALLDONTLIE boost feed acquisition.

No production command registration, model approval, or wagering side effects.
A completed provider response is not evidence of calibrated hit probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

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


def collect_boost_odds(provider, scope: BoostScope, *, game_ids: Iterable[int],
                       max_pages_per_game: int = 100) -> BoostFeedReport:
    """Retrieve only the requested sport's eligible games, fail closed on errors.

    The caller supplies verified BALLDONTLIE game IDs; odds are retained as
    vendor rows, not misrepresented as independent player probabilities.
    """
    sport = VENDOR_SPORT[scope.sport]
    ids = list(game_ids)
    if not ids or len(ids) > 100 or any(
        isinstance(gid, bool) or not isinstance(gid, int) or gid <= 0 for gid in ids
    ):
        raise ValueError("Provide 1-100 valid game IDs")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate game IDs")
    if scope.event_ids and set(map(str, ids)) != scope.event_ids:
        raise ValueError("Game IDs do not match promotion scope")
    rows, errors, pages, succeeded = [], [], 0, 0
    for gid in ids:
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
                rows.append({"sport": scope.sport, "game_id": gid, "vendor": "BALLDONTLIE", "raw": row})
        except BallDontLieError as exc:
            errors.append(f"game:{gid}:{exc}")
            # Stop on entitlement failures and exhausted budget to avoid
            # repeated rejected calls.
            if str(exc) in {"HTTP_401", "HTTP_403", "HTTP_429", "REQUEST_BUDGET_EXHAUSTED"}:
                break
    return BoostFeedReport(
        sport=scope.sport, games_requested=len(ids),
        games_succeeded=succeeded, odds_rows=len(rows), pages=pages,
        coverage="FULL" if succeeded == len(ids) and not errors else
                 "FAILED" if succeeded == 0 else "PARTIAL",
        errors=tuple(errors), rows=tuple(rows),
    )

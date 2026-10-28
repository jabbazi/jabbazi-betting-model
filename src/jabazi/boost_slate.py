"""Bounded, sport-specific game discovery for research-only boost feeds.

This module never invokes the broad scanner. Discovery and paid props are
separate: no sportsbook odds row is evidence of a calibrated hit probability.
No executable ticket or wager recommendation is produced.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jabazi.boost_feed import BoostFeedReport, VENDOR_SPORT, collect_boost_odds
from jabazi.boost_scope import BoostScope
from jabazi.providers.balldontlie import BallDontLieError


@dataclass(frozen=True)
class BoostSlateReport:
    sport: str
    target_date: str
    games_received: int
    games_eligible: int
    game_pages: int
    games_skipped: int
    coverage: str
    errors: tuple[str, ...]
    odds_report: BoostFeedReport | None
    player_probabilities_verified: bool = False


def _nfl_eastern_game_day(value):
    """Convert an explicitly UTC/offset-aware NFL kickoff to Eastern day."""
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.utcoffset() is None:
            return None
        return instant.astimezone(ZoneInfo("America/New_York")).date()
    except (ValueError, TypeError, OverflowError):
        return None


def _matches_vendor_calendar_day(sport: str, value, target: date) -> bool:
    """Compare against the sport's published game day, not raw UTC prefix.

    NFL game timestamps are UTC, so Sunday night ET can be Monday UTC.
    NBA/NHL date-only fields are calendar days. Unparseable/naive NFL
    timestamps fail closed rather than being silently reassigned.
    """
    if not isinstance(value, str):
        return False
    if sport == "nfl":
        return _nfl_eastern_game_day(value) == target
    return value == target.isoformat()


def inspect_sport_slate(provider, scope: BoostScope, *, target_date: date,
                        max_games: int = 25, max_game_pages: int = 10,
                        max_prop_pages: int = 100) -> BoostSlateReport:
    """Discover the specified sport's *scheduled* games and audit paid odds.

    Enforce a hard cap instead of silently treating a truncated slate as full.
    Vendor dates are calendar dates as defined by the sport's API, not inferred
    from local timestamps. Unknown lifecycle/identity yields PARTIAL.
    """
    if not isinstance(target_date, date):
        raise ValueError("A date is required")
    if not 1 <= max_games <= 25:
        raise ValueError("Invalid game cap")
    sport = VENDOR_SPORT[scope.sport]
    label = target_date.isoformat()
    # NFL kickoffs are UTC datetimes. A game on Sunday evening ET may have a
    # Monday UTC date; fetch both dates and filter by the Eastern game day.
    # This remains a SINGLE paginated discovery request (shared page cap).
    game_dates = [label]
    if sport == "nfl":
        game_dates.append((target_date + timedelta(days=1)).isoformat())
    params = [("dates[]", value) for value in game_dates] + [("per_page", 100)]
    try:
        listing = provider.fetch_all_pages(
            sport, "games", params,
            max_pages=max_game_pages,
        )
        if not listing.get("complete"):
            raise BallDontLieError("INCOMPLETE_GAME_PAGINATION")
    except BallDontLieError as exc:
        return BoostSlateReport(
            scope.sport, label, 0, 0, 0, 0, "FAILED",
            (f"GAME_DISCOVERY:{exc}",), None,
        )

    ids = []
    seen = set()
    errors = []
    skipped = 0
    for game in listing["data"]:
        if not isinstance(game, dict):
            errors.append("INVALID_GAME_RECORD")
            continue
        gid = game.get("id")
        if isinstance(gid, bool) or not isinstance(gid, int) or gid <= 0:
            errors.append("INVALID_GAME_ID")
            continue
        if gid in seen:
            errors.append("DUPLICATE_GAME_ID")
            continue
        seen.add(gid)
        date_field = "game_date" if sport == "nhl" else "date"
        game_date = game.get(date_field)
        if not _matches_vendor_calendar_day(sport, game_date, target_date):
            if sport == "nfl":
                actual_day = _nfl_eastern_game_day(game_date)
                if actual_day is not None and abs((actual_day - target_date).days) <= 1:
                    # Widening the UTC query intentionally includes adjacent
                    # Eastern games; never charge paid credits for those.
                    skipped += 1
                    continue
            errors.append("GAME_DATE_NOT_VERIFIED")
            continue
        if game.get("status_state") != "scheduled":
            # Played, in-progress or canceled games are not pregame eligible.
            skipped += 1
            if game.get("status_state") in (None, "unknown"):
                errors.append("GAME_LIFECYCLE_UNVERIFIED")
            continue
        if scope.event_ids and str(gid) not in scope.event_ids:
            skipped += 1
            continue
        ids.append(gid)

    if scope.event_ids and set(map(str, ids)) != scope.event_ids:
        errors.append("PROMOTION_GAMES_NOT_ALL_FOUND")
    if len(ids) > max_games:
        errors.append("GAME_CAP_REACHED_NO_PARTIAL_SCAN")
    if errors:
        return BoostSlateReport(
            scope.sport, label, len(listing["data"]), len(ids),
            listing["pages"], skipped, "PARTIAL", tuple(sorted(set(errors))),
            None,
        )
    if not ids:
        return BoostSlateReport(
            scope.sport, label, len(listing["data"]), 0,
            listing["pages"], skipped, "NO_ELIGIBLE_GAMES", (), None,
        )
    report = collect_boost_odds(
        provider, scope, game_ids=ids,
        max_pages_per_game=max_prop_pages,
    )
    return BoostSlateReport(
        scope.sport, label, len(listing["data"]), len(ids),
        listing["pages"], skipped, report.coverage, report.errors, report,
    )

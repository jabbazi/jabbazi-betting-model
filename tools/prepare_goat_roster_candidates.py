"""Private, read-only NBA/NFL GOAT roster crosswalk candidate probe.

Runs only in an authorized runtime with the existing Sports API key. NBA can
fetch current ESPN rosters; NFL can download the nflverse season roster.
No candidates are automatically verified or promoted to model probabilities.
Logs contain only de-identified counts, never licensed quotes or player IDs.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from jabazi.boost_feed import collect_boost_odds
from jabazi.boost_nba_espn_roster import fetch_nba_espn_roster
from jabazi.boost_nfl_nflverse_roster import fetch_nfl_nflverse_roster
from jabazi.boost_roster_candidates import (
    match_roster_candidates, redacted_candidate_summary,
)
from jabazi.boost_scope import BoostScope, SPORTS
from jabazi.boost_slate import _matches_vendor_calendar_day, _verified_future_kickoff
from jabazi.providers.balldontlie import BallDontLieProvider


def audit_candidate_feed(provider, *, sport, game_id, event_starts_at,
                         source_roster=None, source_loader=None,
                         max_prop_pages=25):
    if sport not in ("NBA", "NFL"):
        raise ValueError("NBA or NFL only")
    if type(game_id) is not int or game_id <= 0:
        raise ValueError("Positive provider game ID required")
    if not 1 <= max_prop_pages <= 100:
        raise ValueError("Bounded page cap required")
    if source_loader is None:
        source_loader = (fetch_nba_espn_roster if sport == "NBA"
                         else fetch_nfl_nflverse_roster)
    base = {
        "sport": sport, "status": "UNAVAILABLE",
        "reason": "PAID_PROP_COVERAGE_NOT_VERIFIED",
        "eligible_quote_rows": 0, "provider_player_rows": 0,
        "candidate_count": 0, "rejections": {},
        "source_identity_reviewed": False,
        "exact_model_inputs_verified": False,
        "model_probabilities_verified": False,
        "betting_enabled": False, "production_approved": False,
    }
    try:
        report = collect_boost_odds(
            provider, BoostScope(SPORTS[sport]),
            game_ids=[game_id], max_pages_per_game=max_prop_pages,
        )
        base["eligible_quote_rows"] = report.odds_rows
        if report.coverage != "FULL" or not report.odds_rows:
            return base
        player_ids = sorted({row["raw"]["player_id"] for row in report.rows})
        if not 1 <= len(player_ids) <= 100:
            base["reason"] = "PLAYER_ID_SCOPE_EXCEEDED"
            return base
        listing = provider.fetch_all_pages(
            sport.lower(), "players",
            [("player_ids[]", ident) for ident in player_ids]
            + [("per_page", 100)], max_pages=5,
        )
        if not listing.get("complete"):
            base["reason"] = "PLAYER_DIRECTORY_PAGINATION_INCOMPLETE"
            return base
        players = listing["data"]
        base["provider_player_rows"] = len(players)
        received = [row.get("id") for row in players if isinstance(row, dict)]
        if (len(received) != len(set(received))
                or set(received) != set(player_ids)):
            base["reason"] = "PLAYER_DIRECTORY_INCOMPLETE_OR_DUPLICATE"
            return base
        if source_roster is None:
            team_abbreviations = {
                row.get("team", {}).get("abbreviation")
                for row in players if isinstance(row.get("team"), dict)
            }
            source_roster = source_loader(team_abbreviations)
        observed_at = datetime.now(UTC)
        result = match_roster_candidates(
            sport, players, source_roster, observed_at=observed_at,
            event_starts_at=event_starts_at,
        )
        base.update(redacted_candidate_summary(result))
        base["status"] = "CANDIDATES_ONLY"
        base["reason"] = "INDEPENDENT_IDENTITY_REVIEW_REQUIRED"
        # Private rows are returned only to the caller; never print this value.
        base["_private_candidates"] = result["candidates_private"]
        return base
    except Exception:
        # Fail closed without logging HTTP bodies, source records or credentials.
        base["reason"] = "PROVIDER_OR_SOURCE_EVIDENCE_UNAVAILABLE"
        return base


def discover_upcoming_games(provider, *, sport, calendar_date, max_games=3):
    """Use authentic provider schedule IDs and kickoffs, never guessed IDs."""
    if sport not in ("NBA", "NFL") or type(calendar_date) is not date:
        raise ValueError("NBA/NFL and explicit date required")
    if not 1 <= max_games <= 3:
        raise ValueError("1-3 game discovery cap required")
    days = [calendar_date.isoformat()]
    if sport == "NFL":
        days.append((calendar_date + timedelta(days=1)).isoformat())
    listing = provider.fetch_all_pages(
        sport.lower(), "games",
        [("dates[]", day) for day in days] + [("per_page", 100)],
        max_pages=5,
    )
    if not listing.get("complete"):
        raise ValueError("Incomplete game discovery")
    now = datetime.now(UTC)
    start_field = "datetime" if sport == "NBA" else "date"
    candidates = []
    seen = set()
    for row in listing["data"]:
        if not isinstance(row, dict):
            continue
        gid = row.get("id")
        if type(gid) is not int or gid <= 0:
            continue
        if gid in seen:
            raise ValueError("Duplicate provider game ID")
        seen.add(gid)
        if (not _matches_vendor_calendar_day(
                sport.lower(), row.get("date"), calendar_date)
                or row.get("status_state") != "scheduled"
                or _verified_future_kickoff(
                    row, sport.lower(), target_date=calendar_date,
                    observed_at=now,
                ) is not None):
            continue
        start = row.get(start_field)
        candidates.append((gid, start))
    return sorted(candidates, key=lambda row: row[1])[:max_games]


def audit_date_candidates(provider, *, sport, calendar_date, source_roster=None,
                          source_loader=None, max_games=3, max_prop_pages=25):
    """Try a bounded upcoming slate and return only de-identified results."""
    base = {
        "sport": sport, "status": "UNAVAILABLE",
        "reason": "NO_VERIFIED_UPCOMING_GAMES",
        "games_considered": 0, "candidate_count": 0,
        "betting_enabled": False, "production_approved": False,
    }
    try:
        games = discover_upcoming_games(
            provider, sport=sport, calendar_date=calendar_date,
            max_games=max_games,
        )
    except Exception:
        base["reason"] = "GAME_DISCOVERY_UNAVAILABLE"
        return base
    last = base
    for game_id, start in games:
        result = audit_candidate_feed(
            provider, sport=sport, game_id=game_id,
            event_starts_at=start, source_roster=source_roster,
            source_loader=source_loader, max_prop_pages=max_prop_pages,
        )
        result["games_considered"] = last.get("games_considered", 0) + 1
        last = result
        if result.get("candidate_count", 0) > 0:
            return result
        if result.get("reason") == "PROVIDER_OR_SOURCE_EVIDENCE_UNAVAILABLE":
            return result
    return last


def _read_private_roster(path):
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("Private roster file missing or too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Private roster must be a list")
    return payload


def _write_private_candidates(path, rows):
    """Exclusive-create 0600 private file. Never overwrite existing evidence."""
    descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(rows, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True, choices=("NBA", "NFL"))
    parser.add_argument("--game-id", type=int)
    parser.add_argument("--starts-at",
                        help="Offset-aware kickoff from independently checked provider game")
    parser.add_argument("--date", type=date.fromisoformat,
                        help="Discover 1-3 authentic upcoming games for this sport")
    parser.add_argument("--max-games", type=int, default=3)
    parser.add_argument("--source-roster-file", type=Path,
                        help="Optional private roster JSON; default uses live ESPN or nflverse")
    parser.add_argument("--save-private-candidates", type=Path)
    parser.add_argument("--max-prop-pages", type=int, default=25)
    parser.add_argument("--request-budget", type=int, default=40)
    args = parser.parse_args(argv)
    if not 1 <= args.request_budget <= 100:
        parser.error("Request budget must be 1-100")
    if not 1 <= args.max_prop_pages <= 100 or args.game_id <= 0:
        parser.error("Invalid page or game bounds")
    try:
        source = (_read_private_roster(args.source_roster_file)
                  if args.source_roster_file is not None else None)
    except (ValueError, OSError, UnicodeError):
        parser.error("Source roster evidence unavailable or invalid")
    key = os.environ.get("JABBAZI_BALLDONTLIE_API_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "UNAVAILABLE", "reason": "SPORTS_API_KEY_NOT_CONFIGURED",
                          "production_approved": False}))
        return 2
    provider = BallDontLieProvider(key, budget=args.request_budget)
    try:
        if args.date is not None:
            result = audit_date_candidates(
                provider, sport=args.sport, calendar_date=args.date,
                source_roster=source, max_games=args.max_games,
                max_prop_pages=args.max_prop_pages,
            )
        else:
            result = audit_candidate_feed(
                provider, sport=args.sport, game_id=args.game_id,
                event_starts_at=args.starts_at, source_roster=source,
                max_prop_pages=args.max_prop_pages,
            )
    finally:
        provider.close()
    private = result.pop("_private_candidates", [])
    if args.save_private_candidates is not None and private:
        try:
            _write_private_candidates(args.save_private_candidates, private)
        except OSError:
            result["private_candidate_file_written"] = False
        else:
            result["private_candidate_file_written"] = True
    print(json.dumps(result, sort_keys=True))
    # A candidate count is NOT verified identity or a model acceptance pass.
    return 0 if result["status"] == "CANDIDATES_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

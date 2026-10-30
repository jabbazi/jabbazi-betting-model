"""Operator-only, read-only acceptance probe for the existing Render runtime.

Run inside an authorized Render shell with the existing BALLDONTLIE secret.
Never print the key, licensed quote rows, player IDs or inferred SGP EV.
The probe does not approve bets, merge code, post to Discord or deploy.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime

from jabazi.boost_scope import BoostScope, SPORTS
from jabazi.boost_market_coverage import summarize_prop_markets
from jabazi.boost_market_manifest import audit_priority_market_presence
from jabazi.boost_slate import inspect_sport_slate
from jabazi.providers.balldontlie import BallDontLieProvider


def audit_sport(provider, *, sport: str, calendar_date: date,
                event_ids=(), markets=(), max_games=25,
                observed_at: datetime | None = None,
                max_prop_pages: int = 25):
    """Return aggregate counts without exposing licensed/player-level payloads."""
    if sport not in SPORTS:
        raise ValueError("Unsupported sport")
    if (not isinstance(calendar_date, date) or not 1 <= max_games <= 25
            or not 1 <= max_prop_pages <= 25):
        raise ValueError("Invalid date, game, or pagination cap")
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Duplicate target game IDs")
    if any(not str(value).isdigit() or int(value) <= 0 for value in event_ids):
        raise ValueError("Invalid target game ID")
    scope = BoostScope(
        SPORTS[sport], frozenset(map(str, event_ids)), frozenset(markets),
    )
    # Paid prop feeds may paginate across many pages for a single game.
    # Read all pages up to a strict cap, then fail closed on truncation.
    result = inspect_sport_slate(
        provider, scope, target_date=calendar_date,
        max_games=max_games, max_game_pages=10,
        max_prop_pages=max_prop_pages,
        require_future_kickoff=True, observed_at=observed_at,
    )
    props = result.odds_report
    breadth = summarize_prop_markets(props.rows if props else ())
    priority = audit_priority_market_presence(
        sport, breadth, eligible_games=result.games_eligible,
    )
    return {
        "provider": "BALLDONTLIE",
        "sport": sport,
        "calendar_date": result.target_date,
        "verified_future_kickoff_required": True,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "game_pages": result.game_pages,
        "games_received": result.games_received,
        "games_eligible": result.games_eligible,
        "games_skipped": result.games_skipped,
        "games_with_prop_response": props.games_succeeded if props else 0,
        "games_with_eligible_quotes": sum(
            count > 0 for _, count in props.game_row_counts
        ) if props else 0,
        "quote_pages": props.pages if props else 0,
        "raw_quotes_received": props.raw_odds_rows if props else 0,
        "eligible_quote_rows": props.odds_rows if props else 0,
        "observed_market_breadth": breadth,
        "priority_market_observations": priority,
        "duplicate_quotes": props.duplicate_rows if props else 0,
        "invalid_quotes": props.invalid_rows if props else 0,
        "foreign_game_quotes": props.mismatched_game_rows if props else 0,
        "stale_quotes": props.stale_rows if props else 0,
        "out_of_scope_quotes": props.out_of_scope_rows if props else 0,
        "coverage": result.coverage,
        "errors": list(result.errors),
        "paid_endpoint_sample_access_observed": bool(
            props is not None and props.games_succeeded > 0
        ),
        "provider_player_hit_probabilities": False,
        "joint_calibration_validated": False,
        "exact_sportsbook_parlay_quote_verified": False,
        "end_to_end_vip_discord_verified": False,
        "production_approved": False,
        "recommendation": "PASS",
        "note": "A completed odds response is not a calibrated joint probability or executable offer.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-sport paid prop coverage probe")
    parser.add_argument("--sport", choices=tuple(SPORTS), required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--game-id", action="append", type=int, default=[])
    parser.add_argument("--market", action="append", default=[])
    parser.add_argument("--max-games", type=int, default=25)
    parser.add_argument("--max-prop-pages", type=int, default=25)
    parser.add_argument("--request-budget", type=int, default=36)
    args = parser.parse_args(argv)
    if (not 1 <= args.max_games <= 25
            or not 1 <= args.max_prop_pages <= 25
            or not 1 <= args.request_budget <= 40):
        parser.error("Invalid bounded audit budget")
    key = os.getenv("JABBAZI_BALLDONTLIE_API_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "UNAVAILABLE", "reason": "PROVIDER_NOT_CONFIGURED",
                          "production_approved": False, "recommendation": "PASS"}))
        return 2
    provider = BallDontLieProvider(key, budget=args.request_budget)
    try:
        result = audit_sport(
            provider, sport=args.sport, calendar_date=args.date,
            event_ids=args.game_id, markets=args.market, max_games=args.max_games,
            max_prop_pages=args.max_prop_pages,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["coverage"] == "FULL" else 1
    finally:
        provider.close()


if __name__ == "__main__":
    raise SystemExit(main())

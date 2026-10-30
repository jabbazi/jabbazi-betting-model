"""Read-only private GOAT-to-fitted-model exact-line acceptance runner.

Fetches actual paid NBA/NFL GOAT sportsbook props and matches them to
independently reviewed local crosswalks, frozen JABBAZI pregame features, and
existing versioned fitted artifacts. No player names, odds, keys, feature rows,
or individual probabilities are printed. No database writes or wagers.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from jabazi.boost_feed import collect_boost_odds
from jabazi.boost_goat_inference_acceptance import audit_exact_line_research
from jabazi.boost_scope import BoostScope, SPORTS
from jabazi.providers.balldontlie import BallDontLieError, BallDontLieProvider


def _private_json(path):
    if not path.is_file() or not 0 < path.stat().st_size <= 2_000_000:
        raise ValueError("Private evidence file missing or outside size bounds")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) > 10000:
        raise ValueError("Expected bounded list of reviewed records")
    return payload


def verify_private_goat_inference(provider, *, sport, game_ids,
                                  crosswalks, snapshots, artifacts,
                                  observed_at=None, max_prop_pages=10):
    if sport not in ("NBA", "NFL"):
        raise ValueError("NBA/NFL only")
    if (not isinstance(game_ids, list) or not 1 <= len(game_ids) <= 3
            or any(type(x) is not int or x <= 0 for x in game_ids)
            or len(set(game_ids)) != len(game_ids)):
        raise ValueError("1-3 unique positive game IDs required")
    if not 1 <= max_prop_pages <= 10:
        raise ValueError("1-10 pages per game")
    base = {
        "sport": sport, "status": "UNAVAILABLE",
        "reason": "PAID_PROP_FEED_NOT_VERIFIED",
        "games_requested": len(game_ids),
        "eligible_quote_rows": 0,
        "exact_line_research_estimates": 0,
        "research_probability_sides": 0,
        "rejections": {},
        "crosswalk_truth_independently_confirmed_by_runtime": False,
        "prospective_calibration_verified": False,
        "joint_probability_verified": False,
        "betting_enabled": False,
        "production_approved": False,
    }
    try:
        feed = collect_boost_odds(
            provider, BoostScope(SPORTS[sport]), game_ids=game_ids,
            max_pages_per_game=max_prop_pages,
        )
    except (BallDontLieError, ValueError):
        base["reason"] = "PAID_PROP_FEED_UNAVAILABLE"
        return base
    base["eligible_quote_rows"] = feed.odds_rows
    if feed.coverage != "FULL" or not feed.odds_rows:
        base["reason"] = "INCOMPLETE_OR_EMPTY_PAID_PROP_FEED"
        return base
    report = audit_exact_line_research(
        sport, feed.rows, crosswalks, snapshots, artifacts,
        observed_at=observed_at or datetime.now(UTC),
    )
    base.update(report)
    base["games_requested"] = len(game_ids)
    base["eligible_quote_rows"] = feed.odds_rows
    base["reason"] = ("UNAPPROVED_EXACT_LINE_RESEARCH"
                      if report["exact_line_research_estimates"]
                      else "NO_VERIFIED_EXACT_LINE_MODEL_INPUTS")
    return base


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True, choices=("NBA", "NFL"))
    parser.add_argument("--game-id", required=True, type=int, action="append")
    parser.add_argument("--reviewed-crosswalks", required=True, type=Path)
    parser.add_argument("--frozen-features", required=True, type=Path)
    parser.add_argument("--fitted-artifacts", required=True, type=Path)
    parser.add_argument("--max-prop-pages", type=int, default=10)
    parser.add_argument("--request-budget", type=int, default=35)
    args = parser.parse_args(argv)
    if (not 1 <= len(args.game_id) <= 3
            or any(x <= 0 for x in args.game_id)
            or len(set(args.game_id)) != len(args.game_id)
            or not 1 <= args.max_prop_pages <= 10
            or not 1 <= args.request_budget <= 40):
        parser.error("Invalid private acceptance request bounds")
    try:
        crosswalks = _private_json(args.reviewed_crosswalks)
        snapshots = _private_json(args.frozen_features)
        artifacts = _private_json(args.fitted_artifacts)
    except (ValueError, OSError, UnicodeError):
        parser.error("Private evidence unavailable or invalid")
    key = os.environ.get("JABBAZI_BALLDONTLIE_API_KEY", "").strip()
    if not key:
        print(json.dumps({
            "status": "UNAVAILABLE", "reason": "SPORTS_API_KEY_NOT_CONFIGURED",
            "production_approved": False,
        }))
        return 2
    provider = BallDontLieProvider(key, budget=args.request_budget)
    try:
        result = verify_private_goat_inference(
            provider, sport=args.sport, game_ids=args.game_id,
            crosswalks=crosswalks, snapshots=snapshots, artifacts=artifacts,
            max_prop_pages=args.max_prop_pages,
        )
    finally:
        provider.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["exact_line_research_estimates"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only private NBA/NFL GOAT-to-frozen-feature acceptance command.

Run from an authorized feature-branch checkout with the existing Sports API
credential and a locally reviewed JSON file of pregame model feature metadata.
No player rows, names, game IDs, odds, features, or credentials are printed.
This checks exact identity joins ONLY, not inference/calibration/SGP approval.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from jabazi.boost_feed import collect_boost_odds
from jabazi.boost_goat_feature_join import audit_exact_model_inputs
from jabazi.boost_scope import BoostScope, SPORTS
from jabazi.providers.balldontlie import BallDontLieError, BallDontLieProvider


def audit_private_feature_join(sport, game_ids, feature_rows, *, provider,
                               observed_at=None):
    if sport not in ("NBA", "NFL"):
        raise ValueError("Only independently authenticated NBA/NFL feeds supported")
    if not 1 <= len(game_ids) <= 5 or len(set(game_ids)) != len(game_ids):
        raise ValueError("1-5 unique game IDs required")
    if any(type(x) is not int or x <= 0 for x in game_ids):
        raise ValueError("Invalid game ID")
    if not isinstance(feature_rows, list) or len(feature_rows) > 10000:
        raise ValueError("Feature metadata must be a bounded list")
    now = observed_at or datetime.now(UTC)
    base = {
        "sport": sport, "observed_at": now.isoformat(),
        "status": "UNAVAILABLE", "reason": "PAID_FEED_NOT_VERIFIED",
        "games_requested": len(game_ids), "quote_rows": 0,
        "feature_rows": len(feature_rows), "exact_versioned_input_matches": 0,
        "rejections": {}, "model_probability_computed": False,
        "calibration_verified": False, "joint_probability_verified": False,
        "betting_enabled": False, "production_approved": False,
    }
    try:
        report = collect_boost_odds(
            provider, BoostScope(SPORTS[sport]),
            game_ids=game_ids, max_pages_per_game=3,
        )
    except (BallDontLieError, ValueError):
        base["reason"] = "SPORTS_API_READ_FAILED"
        return base
    base["quote_rows"] = report.odds_rows
    if report.coverage != "FULL" or not report.odds_rows:
        base["reason"] = "INCOMPLETE_OR_EMPTY_PAID_PROP_COVERAGE"
        return base
    result = audit_exact_model_inputs(
        sport, list(report.rows), feature_rows, observed_at=now,
    )
    base.update({
        "status": "RESEARCH_ONLY",
        "reason": "EXACT_INPUT_MATCH_OBSERVED" if result["exact_versioned_input_matches"]
                  else "NO_VERIFIED_EXACT_INPUT_MATCH",
        "exact_versioned_input_matches": result["exact_versioned_input_matches"],
        "rejections": result["rejections"],
    })
    return base


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True, choices=("NBA", "NFL"))
    parser.add_argument("--game-id", type=int, action="append", required=True)
    parser.add_argument("--feature-file", type=Path, required=True)
    parser.add_argument("--request-budget", type=int, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.request_budget <= 30:
        parser.error("Budget must be 1-30 requests")
    if not 1 <= len(args.game_id) <= 5 or len(set(args.game_id)) != len(args.game_id) or any(x <= 0 for x in args.game_id):
        parser.error("1-5 unique positive game IDs required")
    # File is read locally and never echoed. Keep it out of git and chat.
    if not args.feature_file.is_file() or args.feature_file.stat().st_size > 2_000_000:
        parser.error("Existing feature file must be <=2 MB")
    try:
        features = json.loads(args.feature_file.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        parser.error("Feature JSON invalid")
    if not isinstance(features, list):
        parser.error("Feature JSON must be a list")
    key = os.environ.get("JABBAZI_BALLDONTLIE_API_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "UNAVAILABLE", "reason": "SPORTS_API_KEY_NOT_CONFIGURED",
                          "production_approved": False}))
        return 2
    provider = BallDontLieProvider(key, budget=args.request_budget)
    try:
        result = audit_private_feature_join(
            args.sport, args.game_id, features, provider=provider,
        )
    finally:
        provider.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["exact_versioned_input_matches"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

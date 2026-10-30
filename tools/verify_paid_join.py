"""Run a private, read-only NBA/NFL paid-model-to-odds acceptance probe.

Requires BOTH distinct existing credentials in the authorized environment:
JABBAZI_BALLDONTLIE_LAB_API_KEY and JABBAZI_BALLDONTLIE_API_KEY.
Do not copy keys into logs, GitHub Actions, chat, or preview services.

This probe is NOT a model calibration or wagering approval.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime

from jabazi.boost_feed import collect_boost_odds
from jabazi.boost_paid_join import reconcile_paid_player_research
from jabazi.boost_scope import BoostScope, SPORTS
from jabazi.config import Settings
from jabazi.providers.balldontlie import BallDontLieError, BallDontLieProvider
from jabazi.vip.paid_models import read_paid_player_models


def run(*, sport: str, slate_date: date, game_ids: list[int],
        settings=None, lab_reader=read_paid_player_models, provider_factory=BallDontLieProvider):
    """Returns aggregate allowlisted diagnostics only; never raw player rows."""
    if sport not in ("NBA", "NFL"):
        raise ValueError("LAB player-prop joins are NBA/NFL only")
    if not isinstance(slate_date, date):
        raise ValueError("Date required")
    if not 1 <= len(game_ids) <= 5 or any(type(i) is not int or i <= 0 for i in game_ids) or len(set(game_ids)) != len(game_ids):
        raise ValueError("Provide 1-5 distinct positive game IDs")
    now = datetime.now(UTC)
    result = {
        "sport": sport, "slate_date": slate_date.isoformat(),
        "observed_at": now.isoformat(), "requested_games": len(game_ids),
        "lab_authenticated": False, "lab_prediction_rows": 0,
        "sports_api_complete": False, "sportsbook_prop_rows": 0,
        "exact_identity_joins": 0,
        "identity_namespace_independently_verified": False,
        "calibrated_exact_line_hit_probabilities_verified": False,
        "joint_probability_validated": False,
        "betting_enabled": False, "production_approved": False,
        "status": "UNAVAILABLE", "reason": "MISSING_CREDENTIALS",
    }
    settings = settings or Settings.from_environment()
    if not settings.balldontlie_api_key or not settings.balldontlie_lab_api_key:
        return result
    lab = lab_reader(settings.balldontlie_lab_api_key, sport, slate_date)
    result["lab_authenticated"] = bool(lab.get("coverage_complete"))
    result["lab_prediction_rows"] = len(lab.get("rows", []))
    if lab.get("state") != "RESEARCH_ONLY" or not result["lab_authenticated"] or not result["lab_prediction_rows"]:
        result["reason"] = "LAB_ACCESS_OR_PREDICTIONS_UNVERIFIED"
        return result
    provider = provider_factory(settings.balldontlie_api_key, budget=15)
    try:
        try:
            offers = collect_boost_odds(
                provider, BoostScope(SPORTS[sport]),
                game_ids=game_ids, max_pages_per_game=2,
            )
        except (BallDontLieError, ValueError):
            result["reason"] = "SPORTS_API_READ_FAILED"
            return result
        result["sports_api_complete"] = offers.coverage == "FULL"
        result["sportsbook_prop_rows"] = offers.odds_rows
        if not result["sports_api_complete"] or offers.odds_rows == 0:
            result["reason"] = "SPORTS_API_INCOMPLETE_OR_EMPTY"
            return result
        audit = reconcile_paid_player_research(
            sport, lab["rows"], offers.rows, observed_at=datetime.now(UTC)
        )
        result["exact_identity_joins"] = audit["unique_exact_identity_joins"]
        result["status"] = "RESEARCH_ONLY"
        result["reason"] = (
            "IDENTITY_JOIN_OBSERVED_NOT_VALIDATED"
            if result["exact_identity_joins"] else "NO_EXACT_FRESH_JOIN"
        )
    finally:
        provider.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True, choices=("NBA", "NFL"))
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--game-id", action="append", required=True, type=int)
    args = parser.parse_args(argv)
    report = run(sport=args.sport, slate_date=args.date, game_ids=args.game_id)
    print(json.dumps(report, sort_keys=True))
    # Exit success indicates only complete feed reads and an observed exact join.
    # It NEVER means that probabilities or production wagering are approved.
    return 0 if (report["lab_authenticated"] and report["sports_api_complete"]
                 and report["exact_identity_joins"] > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded three-sport paid-feed acceptance matrix; no automated approval.

Run only in an authorized runtime carrying the EXISTING provider secret.
No secrets, licensed rows, player identifiers, wagers or Discord posts.
This is evidence of provider response and coverage only, not model fitting.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, date, datetime

from jabazi.providers.balldontlie import BallDontLieProvider
from tools.boost_live_acceptance import audit_sport

SPORTS = ("NBA", "NFL", "NHL")
_STOP_CODES = ("HTTP_401", "HTTP_403", "HTTP_429", "REQUEST_BUDGET_EXHAUSTED")


def _public_commit(value: str) -> str | None:
    return value.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", value or "") else None


def audit_matrix(provider, *, target_date: date | None = None,
                 target_dates: dict[str, date] | None = None,
                 max_games: int = 25, runtime_commit: str = "") -> dict:
    """Audit independent NBA/NFL/NHL game days and enforce evidence gates.

    Each league can play on different days. Empty or inaccessible paid
    markets are not proof of entitlement or complete quote coverage.
    """
    days = dict(target_dates or {})
    if target_date is not None:
        for sport in SPORTS:
            days.setdefault(sport, target_date)
    if not 1 <= max_games <= 25:
        raise ValueError("Invalid bounded 1-25 game cap")
    if (set(days) != set(SPORTS)
            or any(type(day) is not date for day in days.values())):
        raise ValueError("Explicit valid NBA/NFL/NHL dates required")
    results = {}
    halt_reason = None
    for sport in SPORTS:
        if halt_reason:
            results[sport] = {
                "coverage": "NOT_CHECKED",
                "errors": ["SKIPPED_AFTER_PROVIDER_ACCESS_OR_BUDGET_FAILURE"],
                "eligible_quote_rows": 0,
                "paid_endpoint_sample_access_observed": False,
            }
            continue
        try:
            report = audit_sport(
                provider, sport=sport, calendar_date=days[sport], max_games=max_games,
            )
        except Exception:
            # Never display transport exceptions, provider response bodies, or keys.
            report = {
                "sport": sport, "coverage": "FAILED",
                "errors": ["PROBE_EXCEPTION"], "eligible_quote_rows": 0,
                "paid_endpoint_sample_access_observed": False,
            }
        results[sport] = report
        if any(
            any(code in str(err) for code in _STOP_CODES)
            for err in report.get("errors", [])
        ):
            halt_reason = "PROVIDER_ENTITLEMENT_RATE_LIMIT_OR_BUDGET_FAILURE"
    complete = all(
        results[sport].get("coverage") == "FULL"
        and results[sport].get("games_eligible", 0) > 0
        and results[sport].get("games_with_prop_response", 0)
            == results[sport].get("games_eligible", -1)
        and results[sport].get("games_with_eligible_quotes", 0)
            == results[sport].get("games_eligible", -1)
        and results[sport].get("eligible_quote_rows", 0) > 0
        and not results[sport].get("errors")
        for sport in SPORTS
    )
    return {
        "schema_version": 1,
        "environment_commit": _public_commit(runtime_commit),
        "target_calendar_dates": {sport: days[sport].isoformat() for sport in SPORTS},
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "sports": results,
        "all_three_paid_quote_coverage_observed": complete,
        "scope": "provider live props only; not model forecasts or SGP quotes",
        "halt_reason": halt_reason,
        "joint_probability_calibration_validated": False,
        "sportsbook_combined_sgp_quote_verified": False,
        "vip_discord_end_to_end_verified": False,
        "production_approved": False,
        "betting_decision": "PASS",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only NBA/NFL/NHL live prop acceptance matrix",
    )
    parser.add_argument("--date", type=date.fromisoformat,
                        help="Common date fallback, overridden by per-sport dates")
    for label in SPORTS:
        parser.add_argument(
            "--" + label.lower() + "-date",
            type=date.fromisoformat,
            help="Sport's verified upcoming pregame calendar date",
        )
    parser.add_argument("--max-games", type=int, default=25)
    parser.add_argument("--request-budget", type=int, default=90)
    args = parser.parse_args(argv)
    if not 1 <= args.max_games <= 25 or not 3 <= args.request_budget <= 120:
        parser.error("Use 1-25 games and a 3-120 request safety budget")
    dates = {
        label: getattr(args, label.lower() + "_date") or args.date
        for label in SPORTS
    }
    if any(day is None for day in dates.values()):
        parser.error("Specify --date or all three --nba-date/--nfl-date/--nhl-date")
    credential = os.environ.get("JABBAZI_BALLDONTLIE_API_KEY", "").strip()
    if not credential:
        print(json.dumps({
            "status": "UNAVAILABLE", "reason": "PROVIDER_NOT_CONFIGURED",
            "production_approved": False, "betting_decision": "PASS",
        }))
        return 2
    provider = BallDontLieProvider(credential, budget=args.request_budget)
    try:
        report = audit_matrix(
            provider, target_dates=dates, max_games=args.max_games,
            runtime_commit=os.environ.get("RENDER_GIT_COMMIT", ""),
        )
        print(json.dumps(report, sort_keys=True))
        return 0 if report["all_three_paid_quote_coverage_observed"] else 1
    finally:
        provider.close()


if __name__ == "__main__":
    raise SystemExit(main())

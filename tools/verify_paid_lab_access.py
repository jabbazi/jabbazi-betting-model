"""Read-only BDL LAB paid player-prop access acceptance.

Run from an *authorized private runtime* with JABBAZI_BALLDONTLIE_LAB_API_KEY.
Do not use the separate JABBAZI_BALLDONTLIE_API_KEY Sports API credential.
No secrets, raw licensed player records, model identifiers, or quotes are logged.
No models are created, predictions generated, subscription changes made, or bets placed.
NHL is explicitly unsupported for LAB player props (game models only).
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from jabazi.config import Settings
from jabazi.vip.paid_models import read_paid_player_models

CST = ZoneInfo("America/Chicago")


def summarized(report: dict) -> dict:
    """Return fixed allowlisted fields; never expose original licensed rows."""
    return {
        "provider": "BALLDONTLIE_LAB",
        "sport": report["sport"],
        "slate_date": report["slate_date"],
        "observed_at": report["observed_at"],
        "state": report["state"],
        "reason": report["reason"],
        "source_player_prop_supported": report["source_player_prop_supported"],
        "models_found": report["models_found"],
        "models_checked": report["models_checked"],
        "predictions_seen": report["predictions_seen"],
        "visible_research_rows": len(report["rows"]),
        "coverage_complete": report["coverage_complete"],
        "lab_endpoint_authenticated": report["coverage_complete"] and report["state"] in ("RESEARCH_ONLY", "NO_PREDICTIONS"),
        "saved_player_predictions_observed": report["state"] == "RESEARCH_ONLY" and len(report["rows"]) > 0,
        "model_hit_probabilities_verified": False,
        "betting_enabled": False,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", type=date.fromisoformat,
                   default=datetime.now(UTC).astimezone(CST).date(),
                   help="Explicit YYYY-MM-DD date; current Chicago date by default")
    p.add_argument("--sport", choices=("NBA", "NFL", "NHL", "ALL"), default="ALL")
    args = p.parse_args(argv)
    key = Settings.from_environment().balldontlie_lab_api_key
    sports = ("NBA", "NFL", "NHL") if args.sport == "ALL" else (args.sport,)
    results = [
        summarized(read_paid_player_models(key, sport, args.date))
        for sport in sports
    ]
    print(json.dumps({
        "checked_at": datetime.now(UTC).isoformat(),
        "release_approved": False,
        "paid_player_hit_probabilities_verified": False,
        "notes": "LAB access, saved predictions and calibrated JABBAZI exact-line hit probabilities are independent release gates.",
        "results": results,
        "notice": ("Passing LAB access alone does not prove complete live odds coverage, "
                   "calibrated player hit probabilities, or production readiness."),
    }, sort_keys=True))
    # A supported sport must have *observed saved predictions*, not only
    # authenticated endpoint access, to pass this feed-readiness checkpoint.
    # It still cannot approve a wager, probability, or production release.
    return 0 if all(
        r["saved_player_predictions_observed"] is True
        if r["sport"] in ("NBA", "NFL") else
        r["reason"] == "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED"
        for r in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

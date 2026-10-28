"""Read-only BDL LAB paid player-prop access acceptance.

Run from the *authorized private service runtime* with the existing BDL key.
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
        "results": results,
        "notice": ("Passing LAB access alone does not prove complete live odds coverage, "
                   "calibrated player hit probabilities, or production readiness."),
    }, sort_keys=True))
    # Zero means the requested *supported* sports passed a complete
    # authenticated API read, never that a model/probability was approved.
    # NHL's unsupported result is expected and never counted as paid coverage.
    return 0 if all(
        r["coverage_complete"] is True
        if r["sport"] in ("NBA", "NFL") else
        r["reason"] == "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED"
        for r in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

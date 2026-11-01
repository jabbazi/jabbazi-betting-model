"""Authorized V7 paid-player scan acceptance; aggregate output, never wagers.

Default is configuration validation only. --execute makes bounded paid requests
and appends private evidence/forecast records in the existing database. It does
not merge/deploy, change credentials, promote models, or publish to Discord.
"""
import argparse
from datetime import date
import json
import uuid

from jabazi.config import Settings
from jabazi.models.player_registry import load_player_models
from jabazi.paid_player_scan import PaidScanLimits, run_paid_player_scan
from jabazi.providers.player_features_live import LivePlayerFeatureCollector


def summary(report):
    sports = {}
    for sport, row in report.get("sports", {}).items():
        sports[sport] = {k: row.get(k) for k in (
            "coverage", "eligible_games", "accepted_quotes", "raw_quotes_received", "pages",
            "requested_games", "responded_games", "model_probability_rows", "model_estimates_complete",
            "errors", "rejections", "prospective_capture",
        )}
        lab = row.get("lab", {})
        sports[sport]["lab"] = {k: lab.get(k) for k in ("state", "reason", "coverage_complete", "models_found", "predictions_seen")}
    observed = bool(sports) and all(
        (row.get("responded_games") or 0) > 0 and (row.get("accepted_quotes") or 0) > 0
        for row in sports.values()
    )
    return {"paid_endpoints_observed_for_requested_sports": observed,
            "status": report.get("status"), "scope_complete": report.get("scope_complete", False),
            "collection_complete": report.get("collection_complete", False),
            "model_scope_complete": report.get("model_scope_complete", False),
            "observed_at": report.get("observed_at"), "slate_date": report.get("slate_date"),
            "paid_requests_made": report.get("paid_requests_made", 0), "stop_reason": report.get("stop_reason"),
            "sports": sports, "betting_enabled": False, "production_approved": False,
            "joint_calibration_validated": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", action="append", choices=("NBA", "NFL", "NHL"))
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    sports = tuple(args.sport or ("NBA", "NFL", "NHL"))
    if len(sports) != len(set(sports)):
        parser.error("Duplicate sports are not allowed")
    store = None
    owner = str(uuid.uuid4())
    try:
        limits = PaidScanLimits.from_environment()
        settings = Settings.from_environment()
        if not args.execute:
            print(json.dumps({"mode": "DRY_RUN", "sports": sports,
                              "sports_key_configured": bool(settings.balldontlie_api_key),
                              "lab_key_configured": bool(settings.balldontlie_lab_api_key),
                              "maximum_requests": limits.requests, "maximum_seconds": limits.seconds,
                              "paid_requests_made": 0, "database_writes": False,
                              "production_approved": False}))
            return 0
        from jabazi.api import platform_store
        store = platform_store()
        if not store.acquire_lease("scanner", owner, 600):
            print(json.dumps({"status": "UNAVAILABLE", "reason": "SCANNER_BUSY", "production_approved": False}))
            return 1
        models, errors = load_player_models(store)
        report = run_paid_player_scan(
            store, settings, models, lambda: store.acquire_lease("scanner", owner, 600),
            limits=limits, sports=sports, slate_date=args.date,
            feature_collector=LivePlayerFeatureCollector(sportsdataio_api_key=settings.sportsdataio_api_key),
        )
        output = summary(report)
        output["model_load_error_count"] = len(errors)
        print(json.dumps(output, sort_keys=True))
        return 0 if output["scope_complete"] and output["paid_endpoints_observed_for_requested_sports"] else 1
    except Exception:
        # Full exception strings can contain provider URLs, DB credentials or
        # paid response data. The operator inspects private service diagnostics.
        print(json.dumps({"status": "UNAVAILABLE", "reason": "V7_PRIVATE_ACCEPTANCE_FAILED",
                          "production_approved": False}))
        return 2
    finally:
        if store is not None:
            try:
                store.release_lease("scanner", owner)
            finally:
                store.close()


if __name__ == "__main__":
    raise SystemExit(main())

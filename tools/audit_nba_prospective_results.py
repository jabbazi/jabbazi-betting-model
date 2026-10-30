"""Private, read-only-by-default NBA prospective-result settlement audit.

Uses authenticated final BALLDONTLIE game/boxscore responses and a private,
independently reviewed ESPN<->BALLDONTLIE crosswalk. Only matches existing
immutable pregame JABBAZI forecasts. Never invents DNP zeros or closing odds.
Database writes require explicit --commit-reviewed-results and do not
constitute calibration or wagering approval.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from jabazi.boost_nba_final_labels import prepare_nba_final_labels
from jabazi.persistence.store import Store
from jabazi.providers.balldontlie import BallDontLieProvider
from jabazi.research.player_prospective import (
    _trusted_forecast, _timestamp, archive_player_result,
)


def audit_nba_result_settlement(provider, store, *, game_id, game_date,
                                reviewed_crosswalks, commit=False):
    if type(game_id) is not int or game_id <= 0 or type(game_date) is not date:
        raise ValueError("Positive NBA game ID and explicit calendar date required")
    if not isinstance(reviewed_crosswalks, list) or len(reviewed_crosswalks) > 200:
        raise ValueError("Bounded reviewed identity records required")
    base = {
        "sport": "NBA", "status": "UNAVAILABLE",
        "reason": "FINAL_GAME_OR_STATS_UNVERIFIED",
        "final_market_labels_prepared": 0,
        "matched_trusted_frozen_forecasts": 0,
        "new_results_archived": 0, "rejections": {},
        "write_requested": bool(commit),
        "calibration_validated": False,
        "betting_enabled": False, "production_approved": False,
    }
    try:
        listing = provider.fetch_all_pages(
            "nba", "games", [("dates[]", game_date.isoformat()), ("per_page", 100)],
            max_pages=5,
        )
        if not listing.get("complete"):
            return base
        matches = [x for x in listing["data"] if isinstance(x, dict) and x.get("id") == game_id]
        if len(matches) != 1:
            base["reason"] = "GAME_ID_NOT_UNIQUE_OR_NOT_FOUND"
            return base
        game = matches[0]
        if game.get("status_state") != "final":
            base["reason"] = "GAME_NOT_FINAL"
            return base
        stats = provider.fetch_all_pages(
            "nba", "stats", [("game_ids[]", game_id), ("per_page", 100)],
            max_pages=10,
        )
        if not stats.get("complete"):
            base["reason"] = "INCOMPLETE_FINAL_STATS_PAGINATION"
            return base
        labels = prepare_nba_final_labels(
            game, stats["data"], reviewed_crosswalks,
            observed_at=datetime.now(UTC),
        )
        base["final_market_labels_prepared"] = labels["final_market_labels_prepared"]
        base["rejections"] = labels["rejections"]
        prepared = labels["_private_result_rows"]
        event_ids = {row["event_id"] for row in prepared}
        if len(event_ids) > 2:
            base["reason"] = "AMBIGUOUS_CANONICAL_EVENT_ID"
            return base
        frozen = []
        for event_id in event_ids:
            frozen.extend(store.list_records(
                "player_prospective_forecast", 1000, entity=event_id,
            ))
        trusted = set()
        for record in frozen:
            f = record["payload"]
            try:
                if (f.get("sport") != "basketball_nba"
                        or not _trusted_forecast(f)
                        or _timestamp(f["predicted_at"]) >= _timestamp(f["starts_at"])):
                    continue
                trusted.add((f["event_id"], f["participant"], f["market"], f["starts_at"]))
            except (KeyError, TypeError, ValueError):
                continue
        matched = []
        for row in prepared:
            key = (row["event_id"], row["participant"], row["market"], row["starts_at"])
            if key in trusted:
                matched.append(row)
        base["matched_trusted_frozen_forecasts"] = len(matched)
        base["status"] = "RESEARCH_ONLY"
        base["reason"] = ("REVIEWED_RESULTS_READY" if matched
                          else "NO_MATCHING_TRUSTED_PREGAME_FORECASTS")
        if commit:
            for row in matched:
                entity = (f"{row['sport']}|{row['event_id']}|"
                          f"{row['participant']}|{row['market']}")
                if store.list_records("player_prospective_result", 1, entity=entity):
                    continue
                archived = archive_player_result(
                    store, sport=row["sport"], event_id=row["event_id"],
                    participant=row["participant"], market=row["market"],
                    observed_value=row["observed_value"],
                    starts_at=row["starts_at"],
                    observed_at=_timestamp(row["observed_at"]),
                    source_checksum=row["source_checksum"],
                    result_status="final",
                )
                base["new_results_archived"] += bool(archived)
        return base
    except Exception:
        # Do not log HTTP response bodies, SQL strings, credentials or player IDs.
        base["reason"] = "PRIVATE_RESULT_EVIDENCE_OR_STORAGE_UNAVAILABLE"
        return base


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", required=True, type=int)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--reviewed-crosswalk-file", required=True, type=Path)
    parser.add_argument("--commit-reviewed-results", action="store_true")
    parser.add_argument("--request-budget", type=int, default=20)
    args = parser.parse_args(argv)
    if args.game_id <= 0 or not 2 <= args.request_budget <= 30:
        parser.error("Invalid game ID or bounded provider budget")
    path = args.reviewed_crosswalk_file
    if not path.is_file() or path.stat().st_size > 2_000_000:
        parser.error("Private reviewed crosswalk file missing or too large")
    try:
        crosswalks = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        parser.error("Private reviewed crosswalk invalid")
    key = os.environ.get("JABBAZI_BALLDONTLIE_API_KEY", "").strip()
    database = os.environ.get("DATABASE_URL", "").strip()
    if not key or not database:
        print(json.dumps({"status": "UNAVAILABLE", "reason": "PRIVATE_RUNTIME_NOT_CONFIGURED",
                          "production_approved": False}))
        return 2
    provider = BallDontLieProvider(key, budget=args.request_budget)
    store = None
    try:
        store = Store(database)
        result = audit_nba_result_settlement(
            provider, store, game_id=args.game_id, game_date=args.date,
            reviewed_crosswalks=crosswalks,
            commit=args.commit_reviewed_results,
        )
    finally:
        provider.close()
        if store is not None:
            store.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "RESEARCH_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Inventory existing local inputs without inventing missing advanced coverage."""

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def inspect(path, kind):
    raw = path.read_bytes()
    result = {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    if kind == "nfl_schedule":
        rows = list(csv.DictReader(raw.decode().splitlines()))
        fields = set(rows[0]) if rows else set()
        result.update(
            records=len(rows),
            fields=sorted(fields),
            has_qb_identity_fields={"home_qb_id", "away_qb_id"} <= fields,
            has_weather_fields={"temp", "wind"} <= fields,
            has_snapshot_observation_field="observed_at" in fields,
            advanced_history_admitted=False,
            reason="Final schedule fields have no verified pregame observation time; no play-by-play",
        )
    else:
        payload = json.loads(raw)
        if kind == "history":
            rows = payload["games"]
            result.update(
                sport=payload["sport"],
                provider=payload.get("provider"),
                games=len(rows),
                odds_with_observation_time=sum(bool(r.get("odds_observed_at")) for r in rows),
                games_with_advanced_feature_snapshot=sum(
                    bool(r.get("advanced_snapshot_id")) for r in rows
                ),
                downloaded_at=payload.get("downloaded_at"),
            )
        else:
            rows = [g for day in payload.get("dates", []) for g in day.get("games", [])]
            result.update(
                games=len(rows),
                team_entries_with_probable_pitcher=sum(
                    bool(t.get("probablePitcher"))
                    for g in rows
                    for t in g.get("teams", {}).values()
                ),
                games_with_boxscore=sum(
                    bool(g.get("boxscore") or g.get("liveData", {}).get("boxscore")) for g in rows
                ),
                advanced_history_admitted=False,
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, action="append", default=[])
    parser.add_argument("--mlb-schedule", type=Path, action="append", default=[])
    parser.add_argument("--nfl-schedule", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = [
        (path, kind)
        for kind in ("history", "mlb_schedule", "nfl_schedule")
        for path in getattr(args, kind)
    ]
    report = {
        "audited_at": datetime.now(UTC).isoformat(),
        "files": [inspect(p, k) for p, k in sources],
        "scope": "Only explicitly listed local files; no cloud credentials or provider entitlements were inspected",
        "trained_advanced_model": False,
        "approved_for_betting": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"files": len(sources), "approved_for_betting": False}))


if __name__ == "__main__":
    main()

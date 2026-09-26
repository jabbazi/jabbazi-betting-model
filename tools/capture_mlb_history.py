"""Capture Retrosheet season archives into staging; no inferred pregame evidence."""

import argparse
import csv
import gzip
import io
import json
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from tools.capture_nfl_context import download, write_json

FIELDS = (
    "gid",
    "id",
    "team",
    "p_seq",
    "p_ipouts",
    "p_bfp",
    "p_k",
    "p_w",
    "p_er",
    "date",
    "number",
    "gametype",
)
COUNTS = ("p_seq", "p_ipouts", "p_bfp", "p_k", "p_w", "p_er")
BATTING_FIELDS = (
    "gid", "id", "team", "b_lp", "b_seq", "b_pa", "b_ab", "b_r", "b_h",
    "b_d", "b_t", "b_hr", "b_rbi", "b_w", "date", "number", "vishome",
    "opp", "gametype",
)
BATTING_COUNTS = ("b_seq", "b_pa", "b_ab", "b_r", "b_h", "b_d", "b_t", "b_hr", "b_rbi", "b_w")
SOURCE = "https://www.retrosheet.org/downloads/"


def season_rows(archive, season):
    """Retain Retrosheet value rows only; bounds/official alternatives aren't new games."""
    with zipfile.ZipFile(archive) as bundle:
        members = [
            info
            for info in bundle.infolist()
            if PurePosixPath(info.filename).name in {"pitching.csv", f"{season}pitching.csv"}
        ]
        if len(members) != 1 or members[0].file_size > 50_000_000:
            raise ValueError("Missing, ambiguous, or oversized pitching CSV")
        with bundle.open(members[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if not set(FIELDS) <= set(reader.fieldnames or []):
                raise ValueError("Pitching schema mismatch: " + str(reader.fieldnames))
            rows, seen, excluded, missing = [], set(), Counter(), Counter()
            for source_row in reader:
                if len(rows) > 50_000:
                    raise ValueError("Season row budget exceeded")
                if source_row.get("stattype", "value") != "value":
                    excluded["non_value_statistics"] += 1
                    continue
                row = {field: source_row[field] for field in FIELDS}
                key = (row["gid"], row["id"], row["team"])
                if not all(key) or key in seen:
                    raise ValueError("Missing or duplicate game/pitcher/team identity")
                seen.add(key)
                date = datetime.strptime(row["date"], "%Y%m%d").date()
                if date.year != season:
                    raise ValueError("Row belongs to a different season")
                for field in COUNTS:
                    if row[field] == "":
                        row[field] = None
                        missing[field] += 1
                    else:
                        value = int(row[field])
                        if value < 0:
                            raise ValueError("Negative pitching count")
                        row[field] = value
                row["season"] = season
                row["observed_at"] = None  # assigned only after the successful capture receipt
                rows.append(row)
    return rows, {
        "season": season,
        "pitcher_game_rows": len(rows),
        "games": len({r["gid"] for r in rows}),
        "pitchers": len({r["id"] for r in rows}),
        "actual_starts": sum(r["p_seq"] == 1 for r in rows),
        "gametypes": dict(Counter(r["gametype"] for r in rows)),
        "missing_counts": dict(missing),
        "excluded": dict(excluded),
    }




def batting_rows(archive, season):
    """Retain one value batting row per player/game/team with no imputed counts."""
    with zipfile.ZipFile(archive) as bundle:
        members = [
            info
            for info in bundle.infolist()
            if PurePosixPath(info.filename).name in {"batting.csv", f"{season}batting.csv"}
        ]
        if len(members) != 1 or members[0].file_size > 80_000_000:
            raise ValueError("Missing, ambiguous, or oversized batting CSV")
        with bundle.open(members[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if not set(BATTING_FIELDS) <= set(reader.fieldnames or []):
                raise ValueError("Batting schema mismatch: " + str(reader.fieldnames))
            rows, seen, excluded, missing = [], set(), Counter(), Counter()
            for source_row in reader:
                if len(rows) > 100_000:
                    raise ValueError("Season batting row budget exceeded")
                if source_row.get("stattype", "value") != "value":
                    excluded["non_value_statistics"] += 1
                    continue
                row = {field: source_row[field] for field in BATTING_FIELDS}
                key = (row["gid"], row["id"], row["team"])
                if not all(key) or key in seen:
                    raise ValueError("Missing or duplicate game/batter/team identity")
                seen.add(key)
                date = datetime.strptime(row["date"], "%Y%m%d").date()
                if date.year != season:
                    raise ValueError("Batting row belongs to a different season")
                for field in BATTING_COUNTS:
                    if row[field] == "":
                        row[field] = None
                        missing[field] += 1
                    else:
                        value = int(row[field])
                        if value < 0:
                            raise ValueError("Negative batting count")
                        row[field] = value
                if row["vishome"] not in {"v", "h"}:
                    raise ValueError("Batting home/away orientation missing")
                row["season"] = season
                row["observed_at"] = None
                rows.append(row)
    return rows, {
        "season": season,
        "batter_game_rows": len(rows),
        "games": len({r["gid"] for r in rows}),
        "batters": len({r["id"] for r in rows}),
        "starting_lineup_rows": sum((r["b_seq"] or 0) == 1 for r in rows),
        "missing_counts": dict(missing),
        "excluded": dict(excluded),
    }


def capture(request_path, output):
    request = json.loads(request_path.read_text())
    if request.get("seasons") != [2021, 2022, 2023, 2024, 2025]:
        raise ValueError("This bounded capture supports only the five approved seasons")
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    # Preserve the publisher's complete terms/attribution notice alongside raw data.
    receipts = [
        download(
            SOURCE + "csvdownloads.html", raw / "RETROSHEET-SOURCE-AND-TERMS.html", limit=500_000
        )
    ]
    reports, batting_reports, total, batting_total = [], [], 0, 0
    with gzip.open(output / "pitching-staging.jsonl.gz", "wt") as pitching_staging, \
         gzip.open(output / "batting-staging.jsonl.gz", "wt") as batting_staging:
        for season in request["seasons"]:
            filename = f"{season}csvs.zip"
            receipt = download(SOURCE + f"{season}/" + filename, raw / filename, limit=40_000_000)
            receipts.append(receipt)
            rows, report = season_rows(raw / filename, season)
            bats, batting_report = batting_rows(raw / filename, season)
            for row in rows:
                row.update(
                    observed_at=receipt["observed_at"],
                    raw_sha256=receipt["sha256"],
                    id_namespace="retrosheet",
                    data_status="STAGING_NOT_MODEL_INPUT",
                )
                pitching_staging.write(json.dumps(row, allow_nan=False) + "\n")
            for row in bats:
                row.update(
                    observed_at=receipt["observed_at"],
                    raw_sha256=receipt["sha256"],
                    id_namespace="retrosheet",
                    data_status="STAGING_NOT_MODEL_INPUT",
                )
                batting_staging.write(json.dumps(row, allow_nan=False) + "\n")
            total += len(rows)
            batting_total += len(bats)
            reports.append(report)
            batting_reports.append(batting_report)
            print(json.dumps({"pitching": report, "batting": batting_report}), flush=True)
    report = {
        "captured_at": datetime.now(UTC).isoformat(),
        "provider": "Retrosheet",
        "per_season": reports,
        "batting_per_season": batting_reports,
        "pitcher_game_rows": total,
        "batter_game_rows": batting_total,
        "status": "STAGING_ONLY",
        "model_fitted": False,
        "approved_for_betting": False,
        "limitations": [
            "No original pregame announcement timestamps",
            "Historical actual starter is not a pregame confirmed starter",
            "Pitch-count workload absent from this pitching schema; never imputed as zero",
            "Canonical mapping to live MLB/odds player and event IDs still required",
            "Dates are retained as dates; no kickoff time or timezone invented",
            "Includes listed game types; filter and reconcile before model admission",
            "No 2026 coverage; archives end in 2025",
            "Batting and pitching logs are final-game outcomes only; all model features must be lagged before admission",
            "Raw Actions artifacts expire after 90 days; preserve before expiry",
        ],
        "attribution_reference": "raw/RETROSHEET-SOURCE-AND-TERMS.html",
    }
    for name, value in (("report", report), ("receipts", receipts), ("request", request)):
        write_json(output / (name + ".json"), value)
    print(json.dumps({k: v for k, v in report.items() if k != "per_season"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    capture(args.request, args.output)

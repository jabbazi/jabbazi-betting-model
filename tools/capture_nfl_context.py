"""Bounded public nflverse capture; never backdates observations or fits models."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jabazi.features.advanced import AdvancedContext, SCHEMA
from jabazi.providers.advanced_stats import nfl_team_snapshots

PBP_COLUMNS = (
    "game_id",
    "play_id",
    "play_type",
    "posteam",
    "defteam",
    "epa",
    "qb_kneel",
    "qb_spike",
)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def download(url, destination, *, limit, sha256=None):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research-Capture/0.1"})
    total, digest = 0, hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("xb") as out:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError("Source download exceeded fixed size budget")
            out.write(chunk)
            digest.update(chunk)
    if sha256 is not None and digest.hexdigest() != sha256:
        raise ValueError("Source changed: digest does not match frozen request")
    return {
        "url": url,
        "file": destination.name,
        "bytes": total,
        "sha256": digest.hexdigest(),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def validate_request(request):
    if request.get("version") != 1 or request.get("provider") != "nflverse":
        raise ValueError("Unsupported capture request")
    if not re.fullmatch(r"[a-f0-9]{40}", request["schedule_commit"]):
        raise ValueError("Immutable schedule commit required")
    seen = set()
    for asset in request["assets"]:
        season = asset["season"]
        filename = f"play_by_play_{season}.csv.gz"
        if (
            type(season) is not int
            or not 2021 <= season <= 2026
            or season in seen
            or asset["filename"] != filename
            or asset["url"]
            != "https://github.com/nflverse/nflverse-data/releases/download/pbp/" + filename
            or not re.fullmatch(r"[a-f0-9]{64}", asset["sha256"])
            or type(asset["size"]) is not int
            or not 0 < asset["size"] < 32_000_000
        ):
            raise ValueError("Invalid, duplicate, unbounded, or non-nflverse asset")
        seen.add(season)
    if not seen:
        raise ValueError("At least one season required")


def schedule_rows(text, seasons):
    games = {}
    for row in csv.DictReader(io.StringIO(text)):
        if int(row["season"]) not in seasons or row["game_type"] not in {
            "REG",
            "WC",
            "DIV",
            "CON",
            "SB",
        }:
            continue
        if not row.get("gametime"):
            continue
        row["starts_at"] = (
            datetime.fromisoformat(row["gameday"] + "T" + row["gametime"])
            .replace(tzinfo=ZoneInfo("America/New_York"))
            .astimezone(UTC)
            .isoformat()
        )
        if row["game_id"] in games:
            raise ValueError("Duplicate scheduled event")
        games[row["game_id"]] = row
    return games


def aggregate_season(path, games, receipt, schedule_receipt, archive_prefix):
    groups, final_scores = defaultdict(list), {}
    total = 0
    with gzip.open(path, "rt", newline="") as source:
        reader = csv.DictReader(source)
        required = set(PBP_COLUMNS) | {
            "home_team",
            "away_team",
            "total_home_score",
            "total_away_score",
        }
        if not required <= set(reader.fieldnames or []):
            raise ValueError("Missing required nflverse columns")
        for row in reader:
            total += 1
            if total > 100_000:
                raise ValueError("Season play count exceeds fixed import budget")
            game = games.get(row["game_id"])
            if not game or not game["home_score"] or not game["away_score"]:
                continue
            if row["home_team"] != game["home_team"] or row["away_team"] != game["away_team"]:
                raise ValueError("Schedule/play-by-play team mismatch")
            groups[row["game_id"]].append({k: row[k] for k in PBP_COLUMNS})
            if row["total_home_score"] not in {"", "NA"} and row["total_away_score"] not in {
                "",
                "NA",
            }:
                final_scores[row["game_id"]] = (
                    float(row["total_home_score"]),
                    float(row["total_away_score"]),
                )
    snapshots, rejected = [], []
    observed = max(receipt["observed_at"], schedule_receipt["observed_at"])
    for gid, plays in sorted(groups.items()):
        game = games[gid]
        if final_scores.get(gid) != (float(game["home_score"]), float(game["away_score"])):
            rejected.append({"event_id": gid, "reason": "final score reconciliation failed"})
            continue
        evidence = {
            "snapshot_id": receipt["sha256"][:16] + ":" + gid,
            "event_id": gid,
            "starts_at": game["starts_at"],
            "completed_by": observed,
            "completion_basis": "final schedule and play-by-play score reconciled at observation; exact end unknown",
            "observed_at": observed,
            "raw_sha256": receipt["sha256"],
            "schedule_sha256": schedule_receipt["sha256"],
            "archive_reference": archive_prefix + "/" + path.name,
        }
        try:
            batch = nfl_team_snapshots(
                plays,
                home_id=game["home_team"],
                away_id=game["away_team"],
                complete_final_game=True,
                evidence=evidence,
            )
        except (ValueError, KeyError) as exc:
            # Record coverage loss; never silently fill missing EPA or duplicate plays.
            rejected.append({"event_id": gid, "reason": str(exc)})
            continue
        snapshots.extend(batch)
    return snapshots, {
        "source_play_rows": total,
        "scheduled_final_games_found": len(groups),
        "games_imported": len(snapshots) // 2,
        "rejected": rejected,
    }


def capture(request_path, output):
    request = json.loads(request_path.read_text())
    validate_request(request)
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    archive_prefix = (
        "github-actions:"
        + os.environ.get("GITHUB_REPOSITORY", "local")
        + ":"
        + os.environ.get("GITHUB_RUN_ID", "local")
        + ":nfl-pbp-source-archives"
    )
    schedule_url = (
        "https://raw.githubusercontent.com/nflverse/nfldata/"
        + request["schedule_commit"]
        + "/data/games.csv"
    )
    schedule_receipt = download(schedule_url, raw / "games.csv", limit=5_000_000)
    games = schedule_rows((raw / "games.csv").read_text(), {a["season"] for a in request["assets"]})
    receipts, snapshots, reports = [schedule_receipt], [], []
    for asset in request["assets"]:
        receipt = download(
            asset["url"], raw / asset["filename"], limit=asset["size"], sha256=asset["sha256"]
        )
        receipt["provider_updated_at"] = asset["provider_updated_at"]
        receipts.append(receipt)
        rows, report = aggregate_season(
            raw / asset["filename"], games, receipt, schedule_receipt, archive_prefix
        )
        snapshots.extend(rows)
        reports.append({"season": asset["season"], **report})
        print(json.dumps(reports[-1]), flush=True)
    document = {
        "manifest": {
            "schema": SCHEMA,
            "provider": "nflverse",
            "id_namespace": "nflverse_game_id_and_team_abbreviation",
            "data_mode": "real",
            "research_rights_reference": request["license_url"],
            "attribution": request["attribution"],
        },
        "snapshots": snapshots,
    }
    context = AdvancedContext(document)
    now = datetime.now(UTC)
    future = [
        g
        for g in games.values()
        if now < datetime.fromisoformat(g["starts_at"]) <= now + timedelta(days=7)
    ]
    results = [
        context.build(
            {
                "event_id": g["game_id"],
                "sport": "americanfootball_nfl",
                "home_id": g["home_team"],
                "away_id": g["away_team"],
                "starts_at": g["starts_at"],
                "prediction_at": now.isoformat(),
            }
        )
        for g in future
    ]
    historical_ready = 0
    for game in games.values():
        if int(game["season"]) > 2025 or not game["home_score"] or not game["away_score"]:
            continue
        decision = datetime.fromisoformat(game["starts_at"]) - timedelta(hours=1)
        row = context.build(
            {
                "event_id": game["game_id"],
                "sport": "americanfootball_nfl",
                "home_id": game["home_team"],
                "away_id": game["away_team"],
                "starts_at": game["starts_at"],
                "prediction_at": decision.isoformat(),
            }
        )
        historical_ready += row["features"] is not None
    report = {
        "captured_at": now.isoformat(),
        "per_season": reports,
        "team_game_snapshots": len(snapshots),
        "upcoming_events": len(results),
        "upcoming_status_counts": dict(Counter(r["status"] for r in results)),
        "historical_training_rows_available": historical_ready,
        "approved_for_betting": False,
        "model_fitted": False,
        "note": "Captured now, not at historical decision times. No historical timestamp fabrication, training, betting approval, or cloud deployment.",
        "limitations": [
            "EPA provider model training vintages are not verified for historical evaluation",
            "Score reconciliation is a provider completeness check, not independent game-log verification",
            "No QB/injury/weather inputs or player-prop distributions",
            "GitHub source artifacts expire after 90 days; export before expiry for long-term raw-source retention",
        ],
    }
    for name, value in (
        ("snapshots", document),
        ("receipts", receipts),
        ("readiness", results),
        ("report", report),
        ("request", request),
    ):
        write_json(output / (name + ".json"), value)
    print(json.dumps({k: v for k, v in report.items() if k != "per_season"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    capture(args.request, args.output)

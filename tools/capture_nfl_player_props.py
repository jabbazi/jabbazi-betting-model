"""Capture nflverse weekly player stats and build leakage-safe rolling prop datasets."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.capture_nfl_context import download, schedule_rows, write_json

MARKETS = {
    "player_pass_yds": ("passing_yards", "attempts", 10.0),
    "player_pass_attempts": ("attempts", "attempts", 10.0),
    "player_pass_completions": ("completions", "attempts", 10.0),
    "player_pass_tds": ("passing_tds", "attempts", 10.0),
    "player_rush_yds": ("rushing_yards", "carries", 2.0),
    "player_rush_attempts": ("carries", "carries", 2.0),
    "player_receptions": ("receptions", "targets", 1.0),
    "player_reception_yds": ("receiving_yards", "targets", 1.0),
    "player_anytime_td": ("anytime_td", "touch_opportunities", 2.0),
}
REQUIRED = {
    "player_id", "player_display_name", "position", "season", "week", "season_type",
    "game_id", "team", "opponent_team", "completions", "attempts", "passing_yards",
    "passing_tds", "carries", "rushing_yards", "rushing_tds", "receptions", "targets",
    "receiving_yards", "receiving_tds",
}


def number(row, name):
    value = row.get(name)
    if value in (None, "", "NA"):
        return 0.0
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Invalid {name}")
    return result


def rolling(values, n):
    subset = list(values)[-n:]
    if not subset:
        return 0.0
    return sum(subset) / len(subset)


def stdev(values, n):
    subset = list(values)[-n:]
    if len(subset) < 2:
        return 0.0
    mean = sum(subset) / len(subset)
    return math.sqrt(sum((v - mean) ** 2 for v in subset) / len(subset))


def build_features(history, opportunity_history, position, is_home):
    games = len(history)
    return {
        "last1_value": history[-1] if history else 0.0,
        "mean3_value": rolling(history, 3),
        "mean5_value": rolling(history, 5),
        "mean10_value": rolling(history, 10),
        "std5_value": stdev(history, 5),
        "season_mean_value": rolling(history, max(1, games)),
        "last1_opportunities": opportunity_history[-1] if opportunity_history else 0.0,
        "mean3_opportunities": rolling(opportunity_history, 3),
        "mean5_opportunities": rolling(opportunity_history, 5),
        "mean10_opportunities": rolling(opportunity_history, 10),
        "games_prior": float(games),
        "is_home": float(is_home),
        "position_qb": float(position == "QB"),
        "position_rb": float(position == "RB"),
        "position_wr": float(position == "WR"),
        "position_te": float(position == "TE"),
    }


def parse_asset(path, schedule):
    rows = []
    with gzip.open(path, "rt", newline="") as source:
        reader = csv.DictReader(source)
        if not REQUIRED <= set(reader.fieldnames or []):
            missing = sorted(REQUIRED - set(reader.fieldnames or []))
            raise ValueError("nflverse weekly schema missing: " + ",".join(missing))
        for row in reader:
            if row.get("season_type") != "REG" or not row.get("player_id") or not row.get("game_id"):
                continue
            game = schedule.get(row["game_id"])
            if not game:
                continue
            if row.get("team") not in {game["home_team"], game["away_team"]}:
                raise ValueError("Player team does not match schedule")
            base = {
                "event_id": row["game_id"],
                "player_id": row["player_id"],
                "participant": row["player_display_name"],
                "position": row.get("position") or "",
                "team": row["team"],
                "opponent": row.get("opponent_team") or "",
                "season": int(row["season"]),
                "week": int(row["week"]),
                "starts_at": game["starts_at"],
                "is_home": row["team"] == game["home_team"],
                "passing_yards": number(row, "passing_yards"),
                "attempts": number(row, "attempts"),
                "completions": number(row, "completions"),
                "passing_tds": number(row, "passing_tds"),
                "carries": number(row, "carries"),
                "rushing_yards": number(row, "rushing_yards"),
                "rushing_tds": number(row, "rushing_tds"),
                "receptions": number(row, "receptions"),
                "targets": number(row, "targets"),
                "receiving_yards": number(row, "receiving_yards"),
                "receiving_tds": number(row, "receiving_tds"),
            }
            base["anytime_td"] = float(base["rushing_tds"] + base["receiving_tds"] > 0)
            base["touch_opportunities"] = base["carries"] + base["targets"]
            rows.append(base)
    return rows


def capture(request_path: Path, output: Path):
    request = json.loads(request_path.read_text())
    if request.get("version") != 1 or request.get("provider") != "nflverse":
        raise ValueError("Unsupported NFL player capture manifest")
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()

    schedule_url = (
        "https://raw.githubusercontent.com/nflverse/nfldata/"
        + request["schedule_commit"]
        + "/data/games.csv"
    )
    schedule_receipt = download(schedule_url, raw / "games.csv", limit=5_000_000)
    schedule = schedule_rows(
        (raw / "games.csv").read_text(),
        set(int(a["season"]) for a in request["assets"]),
    )

    receipts = [schedule_receipt]
    source_rows = []
    digest = hashlib.sha256()
    for asset in request["assets"]:
        receipt = download(
            asset["url"],
            raw / asset["filename"],
            limit=int(asset["size"]) + 1024,
            sha256=asset["sha256"],
        )
        receipts.append(receipt)
        digest.update(receipt["sha256"].encode())
        source_rows.extend(parse_asset(raw / asset["filename"], schedule))

    source_rows.sort(key=lambda r: (r["starts_at"], r["event_id"], r["player_id"]))
    documents = {}
    for market, (value_field, opportunity_field, minimum_opps) in MARKETS.items():
        histories = defaultdict(lambda: deque(maxlen=32))
        opp_histories = defaultdict(lambda: deque(maxlen=32))
        last_starts = {}
        out = []
        for row in source_rows:
            player = row["player_id"]
            values = histories[player]
            opportunities = opp_histories[player]
            if len(values) >= 3 and rolling(opportunities, 3) >= minimum_opps:
                start = datetime.fromisoformat(row["starts_at"].replace("Z", "+00:00"))
                previous = last_starts.get(player)
                # Conservative availability bound: prior game's scheduled start + 12h.
                if previous is not None:
                    feature_available = previous + timedelta(hours=12)
                    prediction = start - timedelta(hours=1)
                    if feature_available < prediction:
                        observed = row[value_field]
                        if market == "player_anytime_td":
                            observed = float(observed > 0)
                        out.append({
                            "event_id": row["event_id"],
                            "player_id": player,
                            "participant": row["participant"],
                            "prediction_at": prediction.astimezone(UTC).isoformat(),
                            "starts_at": start.astimezone(UTC).isoformat(),
                            "features_available_at": feature_available.astimezone(UTC).isoformat(),
                            "result_available_at": (start + timedelta(hours=12)).astimezone(UTC).isoformat(),
                            "result_status": "final",
                            "observed_value": observed,
                            "expected_opportunities": rolling(opportunities, 3),
                            "features": build_features(
                                values, opportunities, row["position"], row["is_home"]
                            ),
                            "availability_basis": "prior_game_scheduled_start_plus_12h",
                        })
            values.append(row[value_field])
            opportunities.append(row[opportunity_field])
            last_starts[player] = datetime.fromisoformat(row["starts_at"].replace("Z", "+00:00"))

        documents[market] = {
            "manifest": {
                "sport": "americanfootball_nfl",
                "market": market,
                "data_mode": "real",
                "provider": "nflverse",
                "source_checksum": digest.hexdigest(),
                "research_rights_reference": request["license_url"],
                "attribution": request["attribution"],
                "evidence_mode": "historical_reconstruction_from_prior_completed_games",
                "market_lines_included": False,
            },
            "rows": out,
        }
        write_json(output / f"{market}.json", documents[market])

    report = {
        "captured_at": datetime.now(UTC).isoformat(),
        "source_player_game_rows": len(source_rows),
        "markets": {market: len(doc["rows"]) for market, doc in documents.items()},
        "model_fitted": False,
        "approved_for_betting": False,
        "limitations": [
            "Historical rows contain no sportsbook prop lines, so they train distributions but do not prove betting edge.",
            "Feature availability is conservatively reconstructed from prior scheduled games; it is not an archived historical observation timestamp.",
            "Production approval still requires frozen prospective predictions, calibration, market comparison, CLV, and clean injury/availability evidence.",
        ],
    }
    write_json(output / "report.json", report)
    write_json(output / "receipts.json", receipts)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    capture(args.request, args.output)

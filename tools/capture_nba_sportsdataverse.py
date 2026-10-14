"""Capture and normalize public SportsDataverse ESPN NBA release data.

The SportsDataverse repository is MIT-licensed; upstream ESPN terms still require
owner review before monetized/commercial use. This tool records that limitation and
never promotes a model.

Outputs:
- nba_team_history.json for the generic score-distribution trainer
- nba_player_history.json for tools/train_nba_player_props.py
"""
import argparse
import csv
import hashlib
import io
import json
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEDULE = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_nba_schedules/nba_schedule_{season}.csv"
)
PLAYER = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_nba_player_boxscores/player_box_{season}.csv"
)
DEFAULT_SEASONS = (2023, 2024, 2025, 2026)


def fetch(url, max_bytes=80_000_000):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.4"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("NBA release asset exceeds capture limit")
    return raw


def truthy(value):
    return str(value).strip().lower() in {"true", "t", "1", "yes"}


def integer(row, key):
    value = row.get(key)
    if value in (None, "", "NA", "NaN"):
        raise ValueError(f"NBA field {key} missing")
    number = float(value)
    if int(number) != number or number < 0:
        raise ValueError(f"NBA field {key} must be a nonnegative integer")
    return int(number)


def number(row, key):
    value = row.get(key)
    if value in (None, "", "NA", "NaN"):
        return 0.0
    return float(value)


def parse_time(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("NBA schedule timestamp must be timezone-aware")
    return dt.astimezone(UTC)


def capture(output, seasons=DEFAULT_SEASONS):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    team_games, player_rows = {}, []
    receipts = []
    schedule_by_game = {}

    for season in seasons:
        for kind, template in (("schedule", SCHEDULE), ("player", PLAYER)):
            url = template.format(season=int(season))
            raw = fetch(url)
            digest = hashlib.sha256(raw).hexdigest()
            receipts.append({
                "kind": kind,
                "season": int(season),
                "url": url,
                "sha256": digest,
                "retrieved_at": datetime.now(UTC).isoformat(),
            })
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            if kind == "schedule":
                required = {
                    "game_id", "season", "season_type", "game_date_time", "neutral_site",
                    "status_type_completed", "home_display_name", "away_display_name",
                    "home_score", "away_score",
                }
                if rows and not required <= set(rows[0]):
                    raise ValueError("SportsDataverse NBA schedule schema mismatch")
                for row in rows:
                    if str(row.get("season_type")) not in {"2", "2.0", "regular-season", "Regular Season"}:
                        continue
                    if not truthy(row.get("status_type_completed")):
                        continue
                    gid = str(row["game_id"])
                    start = parse_time(row["game_date_time"])
                    game = {
                        "game_id": gid,
                        # SportsDataverse NBA release/season labels use the ending
                        # year (2026 = 2025-26). JABBAZI model seasons use the
                        # starting year so chronological split labels stay explicit.
                        "season": int(float(row["season"])) - 1,
                        "starts_at": start.isoformat(),
                        "home_team": str(row["home_display_name"]).strip(),
                        "away_team": str(row["away_display_name"]).strip(),
                        "home_score": integer(row, "home_score"),
                        "away_score": integer(row, "away_score"),
                        "neutral_site": truthy(row.get("neutral_site")),
                        "home_moneyline": None,
                        "away_moneyline": None,
                        "odds_observed_at": None,
                    }
                    if not game["home_team"] or not game["away_team"] or game["home_team"] == game["away_team"]:
                        raise ValueError("Invalid NBA team identity")
                    if gid in team_games and team_games[gid] != game:
                        raise ValueError("Conflicting NBA schedule duplicate")
                    team_games[gid] = game
                    schedule_by_game[gid] = game
            else:
                required = {
                    "game_id", "athlete_id", "athlete_display_name", "minutes", "points",
                    "rebounds", "assists", "three_point_field_goals_made", "blocks",
                    "steals", "turnovers", "home_away", "did_not_play",
                }
                if rows and not required <= set(rows[0]):
                    raise ValueError("SportsDataverse NBA player-box schema mismatch")
                for row in rows:
                    gid = str(row["game_id"])
                    game = schedule_by_game.get(gid)
                    if not game:
                        continue
                    player_id = str(row.get("athlete_id") or "").strip()
                    name = str(row.get("athlete_display_name") or "").strip()
                    if not player_id or not name:
                        continue
                    dnp = truthy(row.get("did_not_play"))
                    minutes = 0.0 if dnp else number(row, "minutes")
                    if not 0 <= minutes <= 70:
                        raise ValueError("NBA player minutes outside supported range")
                    result_at = parse_time(game["starts_at"]) + timedelta(hours=36)
                    player_rows.append({
                        "event_id": gid,
                        "player_id": player_id,
                        "participant": name,
                        "starts_at": game["starts_at"],
                        "result_available_at": result_at.isoformat(),
                        "minutes": minutes,
                        "is_home": str(row.get("home_away") or "").strip().lower() == "home",
                        "points": 0 if dnp else integer(row, "points"),
                        "rebounds": 0 if dnp else integer(row, "rebounds"),
                        "assists": 0 if dnp else integer(row, "assists"),
                        "threes": 0 if dnp else integer(row, "three_point_field_goals_made"),
                        "blocks": 0 if dnp else integer(row, "blocks"),
                        "steals": 0 if dnp else integer(row, "steals"),
                        "turnovers": 0 if dnp else integer(row, "turnovers"),
                    })

    receipt_hash = hashlib.sha256(
        json.dumps(receipts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    team_payload = {
        "provider": "SportsDataverse ESPN NBA schedules",
        "sport": "basketball_nba",
        "source_checksum": receipt_hash,
        "games": sorted(team_games.values(), key=lambda row: (row["starts_at"], row["game_id"])),
    }
    player_payload = {
        "provider": "SportsDataverse ESPN NBA player box scores",
        "source_checksum": receipt_hash,
        "research_rights_reference": (
            "SportsDataverse repository MIT license; upstream ESPN terms require owner review "
            "before monetized/commercial use"
        ),
        "rows": sorted(
            player_rows,
            key=lambda row: (row["starts_at"], row["event_id"], row["player_id"]),
        ),
    }
    (output / "nba_team_history.json").write_text(json.dumps(team_payload, separators=(",", ":")) + "\n")
    (output / "nba_player_history.json").write_text(json.dumps(player_payload, separators=(",", ":")) + "\n")
    (output / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    print(json.dumps({
        "team_games": len(team_games),
        "player_rows": len(player_rows),
        "seasons": list(map(int, seasons)),
        "source_checksum": receipt_hash,
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seasons", nargs="*", type=int, default=list(DEFAULT_SEASONS))
    args = parser.parse_args()
    capture(args.output, tuple(args.seasons))

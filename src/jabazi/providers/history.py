"""Result-history adapters. Raw results are never represented as backtested bets."""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NFL_TEAMS = dict(
    zip(
        "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LA LAC LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split(),
        [
            "Arizona Cardinals",
            "Atlanta Falcons",
            "Baltimore Ravens",
            "Buffalo Bills",
            "Carolina Panthers",
            "Chicago Bears",
            "Cincinnati Bengals",
            "Cleveland Browns",
            "Dallas Cowboys",
            "Denver Broncos",
            "Detroit Lions",
            "Green Bay Packers",
            "Houston Texans",
            "Indianapolis Colts",
            "Jacksonville Jaguars",
            "Kansas City Chiefs",
            "Los Angeles Rams",
            "Los Angeles Chargers",
            "Las Vegas Raiders",
            "Miami Dolphins",
            "Minnesota Vikings",
            "New England Patriots",
            "New Orleans Saints",
            "New York Giants",
            "New York Jets",
            "Philadelphia Eagles",
            "Pittsburgh Steelers",
            "Seattle Seahawks",
            "San Francisco 49ers",
            "Tampa Bay Buccaneers",
            "Tennessee Titans",
            "Washington Commanders",
        ],
    )
)
NFL_TEAMS.update(
    {
        "LAR": "Los Angeles Rams",
        "OAK": "Las Vegas Raiders",
        "SD": "Los Angeles Chargers",
        "STL": "Los Angeles Rams",
        "JAC": "Jacksonville Jaguars",
    }
)
MLB_ALIASES = {"Oakland Athletics": "Athletics", "Cleveland Indians": "Cleveland Guardians"}


def fetch_json(url, headers=None):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Jabbazi-Research/0.2", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def save(rows, provider, sport, output, as_of):
    cutoff = datetime.fromisoformat(as_of).replace(tzinfo=UTC)
    dedup = {}
    for row in rows:
        start = datetime.fromisoformat(row["starts_at"].replace("Z", "+00:00"))
        if start.tzinfo is None:
            raise ValueError("Missing timezone")
        # Completed games from the current UTC date are deliberately excluded.
        if start < cutoff:
            if row["game_id"] in dedup:
                raise ValueError("Duplicate history game")
            dedup[row["game_id"]] = row
    payload = {
        "provider": provider,
        "sport": sport,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "as_of_exclusive_utc": cutoff.isoformat(),
        "games": sorted(dedup.values(), key=lambda g: (g["starts_at"], g["game_id"])),
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    return len(payload["games"])


def nfl_rows(text, seasons):
    rows = []
    for g in csv.DictReader(io.StringIO(text)):
        if int(g["season"]) not in seasons or g["game_type"] not in {
            "REG",
            "WC",
            "DIV",
            "CON",
            "SB",
        }:
            continue
        if not g["home_score"] or not g["away_score"]:
            continue
        if not g.get("gametime") or g.get("location") not in {"Home", "Neutral"}:
            raise ValueError("NFL kickoff or venue context missing")
        dt = (
            datetime.fromisoformat(g["gameday"] + "T" + g["gametime"])
            .replace(tzinfo=ZoneInfo("America/New_York"))
            .astimezone(UTC)
        )
        rows.append(
            {
                "game_id": g["game_id"],
                "season": int(g["season"]),
                "starts_at": dt.isoformat(),
                "home_team": NFL_TEAMS[g["home_team"]],
                "away_team": NFL_TEAMS[g["away_team"]],
                "home_score": int(g["home_score"]),
                "away_score": int(g["away_score"]),
                "neutral_site": g["location"] == "Neutral",
                "home_moneyline": float(g["home_moneyline"]) if g.get("home_moneyline") else None,
                "away_moneyline": float(g["away_moneyline"]) if g.get("away_moneyline") else None,
                # nflverse schedule prices do not supply snapshot timestamps.
                "odds_observed_at": None,
            }
        )
    return rows


def backfill_nfl(seasons, output, as_of, csv_path=None):
    if csv_path:
        text = Path(csv_path).read_text()
    else:
        with urllib.request.urlopen(
            "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv", timeout=45
        ) as r:
            text = r.read().decode()
    return save(nfl_rows(text, seasons), "nflverse/nfldata", "americanfootball_nfl", output, as_of)


def mlb_rows(payload):
    rows = []
    for day in payload.get("dates", []):
        for g in day.get("games", []):
            # abstractGameState='Final' also occurs on postponed records.
            if g.get("status", {}).get("codedGameState") != "F" or g.get("gameType") not in {
                "R",
                "F",
                "D",
                "L",
                "W",
            }:
                continue
            # A suspended game's final score may appear against its original
            # start months earlier. Exclude both entries rather than leak it.
            if g.get("resumeDate") or g.get("resumedFrom"):
                continue
            h, a = g["teams"]["home"], g["teams"]["away"]
            if "score" not in h or "score" not in a:
                continue
            rows.append(
                {
                    "game_id": str(g["gamePk"]),
                    "season": int(g["season"]),
                    "starts_at": g["gameDate"],
                    "home_team": MLB_ALIASES.get(h["team"]["name"], h["team"]["name"]),
                    "away_team": MLB_ALIASES.get(a["team"]["name"], a["team"]["name"]),
                    "home_score": h["score"],
                    "away_score": a["score"],
                    "neutral_site": bool(g.get("isNeutralSite", False)),
                    "home_moneyline": None,
                    "away_moneyline": None,
                    "odds_observed_at": None,
                }
            )
    return rows


def backfill_mlb(seasons, output, as_of):
    rows = []
    for season in sorted(set(seasons)):
        url = "https://statsapi.mlb.com/api/v1/schedule?" + urllib.parse.urlencode(
            {"sportId": 1, "season": season, "gameTypes": "R,F,D,L,W"}
        )
        rows.extend(mlb_rows(fetch_json(url)))
    return save(rows, "MLB Stats API", "baseball_mlb", output, as_of)


def cfb_rows(payload):
    if not isinstance(payload, list):
        raise ValueError("Unexpected CFBD response")
    rows = []
    for g in payload:
        if g.get("completed") is not True:
            continue
        if g.get("homePoints") is None or g.get("awayPoints") is None:
            continue
        if type(g.get("neutralSite")) is not bool:
            raise ValueError("CFB neutral-site status missing")
        rows.append(
            {
                "game_id": str(g["id"]),
                "season": int(g["season"]),
                "starts_at": g["startDate"],
                "home_team": g["homeTeam"],
                "away_team": g["awayTeam"],
                "home_score": g["homePoints"],
                "away_score": g["awayPoints"],
                "neutral_site": g["neutralSite"],
                "home_moneyline": None,
                "away_moneyline": None,
                "odds_observed_at": None,
            }
        )
    return rows


def backfill_cfb(seasons, output, as_of, key):
    if not key:
        raise ValueError("JABBAZI_CFBD_API_KEY is required")
    rows = []
    for season in sorted(set(seasons)):
        for season_type in ("regular", "postseason"):
            url = "https://api.collegefootballdata.com/games?" + urllib.parse.urlencode(
                {"year": season, "seasonType": season_type, "classification": "fbs"}
            )
            rows.extend(cfb_rows(fetch_json(url, {"Authorization": "Bearer " + key})))
    return save(rows, "CollegeFootballData", "americanfootball_ncaaf", output, as_of)

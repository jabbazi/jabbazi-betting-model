"""Zero-odds-credit smoke verification for live player-input sources."""
from __future__ import annotations

import csv
import gzip
import io
import json
import urllib.request
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from jabazi.providers.player_features_live import NFL_DEPTH, NFL_INJURIES


def fetch(url, *, max_bytes=32_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-LiveInputHealth/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("live input response exceeds size limit")
    return raw


def csv_fields(raw, *, gzip_encoded=False):
    if gzip_encoded:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as z:
            text = z.read().decode("utf-8")
    else:
        text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return set(reader.fieldnames or []), next(reader, None)


def verify():
    now = datetime.now(UTC)
    season = now.year if now.month >= 7 else now.year - 1
    report = {}

    depth_url = NFL_DEPTH.replace("2026.csv", f"{season}.csv")
    fields, row = csv_fields(fetch(depth_url))
    required = {"dt", "team", "player_name", "gsis_id", "pos_abb", "pos_rank"}
    if not required <= fields or row is None:
        raise ValueError("NFL depth-chart live schema unhealthy")
    report["nfl_depth"] = {"ok": True, "provider": "nflverse", "season": season}

    injury_url = NFL_INJURIES.replace("2026.csv", f"{season}.csv")
    fields, row = csv_fields(fetch(injury_url))
    required = {"season", "team", "week", "gsis_id", "full_name", "report_status", "date_modified"}
    if not required <= fields or row is None:
        raise ValueError("NFL injury live schema unhealthy")
    report["nfl_injuries"] = {"ok": True, "provider": "nflverse", "season": season}

    local_date = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    mlb = json.loads(fetch(
        "https://statsapi.mlb.com/api/v1/schedule?"
        f"sportId=1&date={local_date}&hydrate=probablePitcher"
    ))
    if not isinstance(mlb.get("dates"), list):
        raise ValueError("MLB StatsAPI schedule schema unhealthy")
    report["mlb_roles"] = {
        "ok": True,
        "provider": "MLB StatsAPI",
        "date": local_date,
        "games": sum(len(day.get("games", [])) for day in mlb["dates"]),
    }

    nhl_roster = json.loads(fetch("https://api-web.nhle.com/v1/roster/FLA/current"))
    if not isinstance(nhl_roster, dict) or not any(
        isinstance(nhl_roster.get(key), list) for key in ("forwards", "defensemen", "goalies")
    ):
        raise ValueError("NHL roster schema unhealthy")
    nhl_injuries = json.loads(fetch(
        "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
    ))
    if not isinstance(nhl_injuries.get("injuries"), list):
        raise ValueError("NHL injury schema unhealthy")
    report["nhl"] = {
        "ok": True,
        "history_roster_provider": "NHL",
        "injury_provider": "ESPN",
        "starting_goalie_verified": False,
    }

    nba_injuries = json.loads(fetch(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
    ))
    if not isinstance(nba_injuries.get("injuries"), list):
        raise ValueError("NBA injury schema unhealthy")
    report["nba_injuries"] = {
        "ok": True,
        "provider": "ESPN",
        "groups": len(nba_injuries["injuries"]),
        "rotation_provider_verified": False,
    }

    print(json.dumps({
        "checked_at": now.isoformat(),
        "odds_provider_credits_used": 0,
        "sources": report,
    }, indent=2))


if __name__ == "__main__":
    verify()

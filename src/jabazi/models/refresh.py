"""Bounded feature/schedule refresh; never retrains or promotes frozen research models."""

import csv
import hashlib
import io
import json
import os
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jabazi.persistence.store import digest
from jabazi.providers.history import NFL_TEAMS, mlb_rows, nfl_rows

from .score_distribution import ScoreDistributionModel, available_at, state_from_games
from .team_elo import SPORTS, timestamp, validate_history

BUNDLE_DIR = Path(__file__).with_name("artifacts")


def schedule_nfl(raw, now):
    events = []
    for r in csv.DictReader(io.StringIO(raw)):
        if r.get("game_type") not in {"REG", "WC", "DIV", "CON", "SB"} or not r.get("gametime"):
            continue
        start = (
            datetime.fromisoformat(r["gameday"] + "T" + r["gametime"])
            .replace(tzinfo=ZoneInfo("America/New_York"))
            .astimezone(UTC)
        )
        if not now < start <= now + timedelta(days=10) or r.get("location") not in {
            "Home",
            "Neutral",
        }:
            continue
        events.append(
            {
                "game_id": r["game_id"],
                "home_team": NFL_TEAMS[r["home_team"]],
                "away_team": NFL_TEAMS[r["away_team"]],
                "starts_at": start.isoformat(),
                "neutral_site": r["location"] == "Neutral",
            }
        )
    return events


def schedule_mlb(raw, now, home_venues=None):
    events = []
    from jabazi.providers.history import MLB_ALIASES

    for day in raw.get("dates", []):
        for r in day.get("games", []):
            start = timestamp(r["gameDate"])
            if not now < start <= now + timedelta(days=10) or r.get("gameType") not in {
                "R",
                "F",
                "D",
                "L",
                "W",
            }:
                continue
            if r.get("status", {}).get("abstractGameState") != "Preview":
                continue
            # Verify the listed venue against current team venue metadata.
            neutral = r.get("isNeutralSite")
            if type(neutral) is not bool:
                home_id = r["teams"]["home"]["team"].get("id")
                home_venue = (home_venues or {}).get(home_id)
                if home_venue is None or r.get("venue", {}).get("id") != home_venue:
                    continue
                neutral = False
            events.append(
                {
                    "game_id": str(r["gamePk"]),
                    "home_team": MLB_ALIASES.get(
                        r["teams"]["home"]["team"]["name"], r["teams"]["home"]["team"]["name"]
                    ),
                    "away_team": MLB_ALIASES.get(
                        r["teams"]["away"]["team"]["name"], r["teams"]["away"]["team"]["name"]
                    ),
                    "starts_at": start.isoformat(),
                    "neutral_site": neutral,
                }
            )
    return events


def update_state(artifact, games, events, *, now, response_checksum):
    short = next(k for k, v in SPORTS.items() if v == artifact["sport"])
    games = validate_history({"sport": artifact["sport"], "games": games}, short)
    recent = [g for g in games if available_at(g) < now]
    if (
        not recent
        or (now - max(timestamp(g["starts_at"]) for g in recent)).total_seconds() > 7 * 86400
    ):
        raise ValueError("Recent completed game coverage unavailable")
    state = state_from_games(recent, now=now, window=artifact["window"])
    # Coverage is replaced, never supplemented with stale unknown result state.
    value = artifact | {
        "team_state": state,
        "events": events,
        "state_refreshed_at": now.isoformat(),
        "state_source_checksum": response_checksum,
        "state_latest_game_at": max(g["starts_at"] for g in recent),
    }
    ScoreDistributionModel(value)
    return value


def fetch_update(artifact, *, now, result_store=None):
    if artifact["sport"] == SPORTS["cfb"]:
        from jabazi.providers.history import fetch_json, cfb_rows
        key = os.getenv("JABBAZI_CFBD_API_KEY", "")
        if not key:
            raise ValueError("CFBD credential unavailable")
        all_rows=[]
        for year in (now.year-1, now.year):
            query = urllib.parse.urlencode({"year":year,"classification":"fbs"})
            all_rows.extend(fetch_json("https://api.collegefootballdata.com/games?"+query,
                                       {"Authorization":"Bearer "+key}))
        # Keep the first production CFB scope identical to training.
        all_rows=[g for g in all_rows if g.get("homeClassification")=="fbs" and g.get("awayClassification")=="fbs"]
        games=cfb_rows(all_rows)
        events=[{"game_id":str(g["id"]),"season":g["season"],"week":g["week"],
                 "home_team":g["homeTeam"],"away_team":g["awayTeam"],
                 "starts_at":g["startDate"],"neutral_site":g["neutralSite"]}
                for g in all_rows if not g.get("completed") and type(g.get("neutralSite")) is bool
                and now < timestamp(g["startDate"]) <= now+timedelta(days=10)]
        raw=json.dumps(all_rows,sort_keys=True).encode()
    elif artifact["sport"] == SPORTS["nfl"]:
        url = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(12_000_001)
        if len(raw) > 12_000_000:
            raise ValueError("NFL response too large")
        text = raw.decode()
        games = nfl_rows(text, {now.year - 1, now.year})
        events = schedule_nfl(text, now)
    else:
        query = urllib.parse.urlencode(
            {
                "sportId": 1,
                "startDate": (now - timedelta(days=65)).date().isoformat(),
                "endDate": (now + timedelta(days=10)).date().isoformat(),
                "gameTypes": "R,F,D,L,W",
            }
        )
        with urllib.request.urlopen(
            "https://statsapi.mlb.com/api/v1/schedule?" + query, timeout=30
        ) as response:
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("MLB response too large")
        payload = json.loads(raw)
        games = mlb_rows(payload)
        with urllib.request.urlopen(
            "https://statsapi.mlb.com/api/v1/teams?sportId=1", timeout=30
        ) as response:
            team_raw = response.read(1_000_001)
        if len(team_raw) > 1_000_000:
            raise ValueError("MLB team response too large")
        teams = json.loads(team_raw)
        venues = {t["id"]: t["venue"]["id"] for t in teams["teams"] if t.get("venue", {}).get("id")}
        events = schedule_mlb(payload, now, venues)
        raw += team_raw
    checksum = hashlib.sha256(raw).hexdigest()
    updated = update_state(artifact, games, events, now=now, response_checksum=checksum)
    if result_store is not None:
        from jabazi.research.prospective import archive_results
        archive_results(result_store, artifact["sport"],
                        [g for g in games if available_at(g) < now
                         and timestamp(g["starts_at"]) >= now - timedelta(days=30)],
                        observed_at=now, source_checksum=checksum)
    return updated


def refresh_models(store, *, now=None):
    now = now or datetime.now(UTC)
    owner = str(uuid.uuid4())
    if not store.acquire_lease("model_refresh", owner, 300):
        return {"status": "BUSY"}
    report = {}
    try:
        sports = ("nfl", "mlb", "cfb") if os.getenv("JABBAZI_CFBD_API_KEY") else ("nfl", "mlb")
        for short in sports:
            previous = store.list_records("model_refresh_attempt", 1, entity=SPORTS[short])
            if previous:
                elapsed = (now - timestamp(previous[0]["payload"]["attempted_at"])).total_seconds()
                if 0 <= elapsed < 6 * 3600:
                    report[short] = "NOT_DUE"
                    continue
            store.append("model_refresh_attempt", SPORTS[short], {"attempted_at": now.isoformat()})
            try:
                path = BUNDLE_DIR / f"{short}_scores.json"
                artifact = json.loads(path.read_text())
                updated = fetch_update(artifact, now=now, result_store=store)
                key = digest(["game_model", updated])
                store.append("game_model", SPORTS[short], updated, key)
                report[short] = {
                    "status": "SHADOW_READY",
                    "version": updated["model_version"],
                    "teams": len(updated["team_state"]),
                    "events": len(updated["events"]),
                }
            except Exception as exc:  # noqa: BLE001 -- preserve failure marker without credential text
                # Fail closed with a marker; readers cannot silently fall back to older state.
                store.append(
                    "game_model",
                    SPORTS[short],
                    {
                        "status": "UNAVAILABLE",
                        "sport": SPORTS[short],
                        "attempted_at": now.isoformat(),
                        "error_type": type(exc).__name__,
                    },
                )
                report[short] = {"status": "UNAVAILABLE", "error_type": type(exc).__name__}
        store.append(
            "model_refresh_result",
            "score_models",
            {"completed_at": now.isoformat(), "models": report},
        )
        return report
    finally:
        store.release_lease("model_refresh", owner)

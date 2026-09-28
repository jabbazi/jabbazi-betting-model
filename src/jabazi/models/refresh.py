"""Bounded feature/schedule refresh; never retrains or promotes frozen research models."""

import csv
import hashlib
import io
import json
import os
import urllib.error
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


def nba_schedule_rows(raw, now):
    """Normalize SportsDataverse NBA schedule rows for state refresh."""
    games, events = [], []
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        if str(row.get("season_type")) not in {"2", "2.0", "regular-season", "Regular Season"}:
            continue
        try:
            start = timestamp(str(row["game_date_time"]).replace("Z", "+00:00"))
            season = int(float(row["season"])) - 1
            home = str(row["home_display_name"]).strip()
            away = str(row["away_display_name"]).strip()
            neutral = str(row.get("neutral_site", "")).strip().lower() in {"true", "t", "1", "yes"}
            completed = str(row.get("status_type_completed", "")).strip().lower() in {
                "true", "t", "1", "yes"
            }
            gid = str(row["game_id"])
            if not gid or not home or not away or home == away:
                raise ValueError("Invalid NBA schedule identity")
            if completed:
                hs, aws = int(float(row["home_score"])), int(float(row["away_score"]))
                if min(hs, aws) < 0:
                    raise ValueError("Invalid NBA final score")
                games.append({
                    "game_id": gid,
                    "season": season,
                    "starts_at": start.isoformat(),
                    "home_team": home,
                    "away_team": away,
                    "home_score": hs,
                    "away_score": aws,
                    "neutral_site": neutral,
                    "home_moneyline": None,
                    "away_moneyline": None,
                    "odds_observed_at": None,
                })
            elif now < start <= now + timedelta(days=10):
                events.append({
                    "game_id": gid,
                    "season": season,
                    "home_team": home,
                    "away_team": away,
                    "starts_at": start.isoformat(),
                    "neutral_site": neutral,
                })
        except (KeyError, TypeError, ValueError):
            continue
    return games, events


def update_state(artifact, games, events, *, now, response_checksum, allow_stale_state=False):
    short = next(k for k, v in SPORTS.items() if v == artifact["sport"])
    games = validate_history({"sport": artifact["sport"], "games": games}, short)
    recent = [g for g in games if available_at(g) < now]
    if not recent:
        raise ValueError("Completed game coverage unavailable")
    if (
        not allow_stale_state
        and (now - max(timestamp(g["starts_at"]) for g in recent)).total_seconds() > 7 * 86400
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
    if artifact["sport"] == SPORTS["nhl"]:
        from .nhl_refresh import fetch_update as fetch_nhl
        return fetch_nhl(artifact, now=now, result_store=result_store)
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
    elif artifact["sport"] == SPORTS["nba"]:
        ending_year = now.year + 1 if now.month >= 7 else now.year
        candidates = (ending_year, ending_year - 1) if now.month < 10 else (ending_year,)
        raw = None
        games, events = [], []
        for season_file in candidates:
            url = (
                "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
                f"espn_nba_schedules/nba_schedule_{season_file}.csv"
            )
            try:
                with urllib.request.urlopen(url, timeout=45) as response:
                    candidate_raw = response.read(20_000_001)
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and season_file != candidates[-1]:
                    continue
                raise
            if len(candidate_raw) > 20_000_000:
                raise ValueError("NBA schedule response too large")
            candidate_games, candidate_events = nba_schedule_rows(candidate_raw, now)
            # Before October an upcoming-season release may exist as an empty
            # placeholder. Fall back to the latest completed-season file rather
            # than poisoning the model state with an empty refresh.
            if candidate_games or candidate_events or season_file == candidates[-1]:
                raw = candidate_raw
                games, events = candidate_games, candidate_events
                break
        if raw is None:
            raise ValueError("NBA schedule response unavailable")
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
    allow_stale_state = (
        artifact["sport"] == SPORTS["nba"]
        and now.month < 10
        and not events
    )
    updated = update_state(
        artifact,
        games,
        events,
        now=now,
        response_checksum=checksum,
        allow_stale_state=allow_stale_state,
    )
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
        sports = ["nfl", "mlb", "nhl"]
        if os.getenv("JABBAZI_CFBD_API_KEY"):
            sports.append("cfb")
        if (BUNDLE_DIR / "nba_scores.json").exists():
            sports.append("nba")
        sports = tuple(sports)
        for short in sports:
            # Renew between bounded providers: combined multi-sport requests can
            # exceed the original lease lifetime during a slow feed response.
            if not store.acquire_lease("model_refresh", owner, 300):
                return {"status": "LEASE_LOST", "models": report}
            previous = store.list_records("model_refresh_attempt", 1, entity=SPORTS[short])
            if previous:
                elapsed = (now - timestamp(previous[0]["payload"]["attempted_at"])).total_seconds()
                latest = store.list_records("game_model", 1, entity=SPORTS[short])
                failed = bool(latest and latest[0]["payload"].get("status") == "UNAVAILABLE")
                retry_after = 60 if failed else 6 * 3600
                if 0 <= elapsed < retry_after:
                    report[short] = "NOT_DUE"
                    continue
            store.append("model_refresh_attempt", SPORTS[short], {"attempted_at": now.isoformat()})
            try:
                path = BUNDLE_DIR / ("nhl_goals.json" if short == "nhl" else f"{short}_scores.json")
                artifact = json.loads(path.read_text())
                if short == "nhl":
                    prior = store.list_records("game_model", 1, entity=SPORTS[short])
                    if prior and prior[0]["payload"].get("model_version") == artifact["model_version"]:
                        artifact = prior[0]["payload"]
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
                report[short] = {
                    "status": "UNAVAILABLE",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                }
        store.append(
            "model_refresh_result",
            "score_models",
            {"completed_at": now.isoformat(), "models": report},
        )
        return report
    finally:
        store.release_lease("model_refresh", owner)

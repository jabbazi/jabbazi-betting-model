"""Bounded public archive capture. Internal research; no commercial license inferred."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import urllib.request

BASE = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/"


def normalize(records, now):
    games = []
    events = []
    seen = set()
    for g in records:
        if g.get("fbs_game") is not True or g.get("start_time_tbd") is not False:
            continue  # Initial lane is FBS-v-FBS only; no inferred FCS strength.
        if not isinstance(g.get("neutral_site"), bool):
            continue
        start = datetime.fromisoformat(g["start_date"].replace("Z", "+00:00"))
        if start.tzinfo is None:
            raise ValueError("Unzoned CFB date")
        key = str(g["game_id"])
        if key in seen:
            raise ValueError("Duplicate CFB event")
        seen.add(key)
        common = dict(
            game_id=key,
            season=int(g["season"]),
            week=int(g["week"]),
            starts_at=start.isoformat(),
            home_team=g["home_team"],
            away_team=g["away_team"],
            home_team_id=str(g["home_id"]),
            away_team_id=str(g["away_id"]),
            neutral_site=g["neutral_site"],
            home_moneyline=None,
            away_moneyline=None,
            odds_observed_at=None,
        )
        if g.get("completed") is True and g.get("status") == "STATUS_FINAL":
            if start >= now:
                raise ValueError("Future completed game")
            h, a = g["home_points"], g["away_points"]
            if h is None or a is None or h < 0 or a < 0 or int(h) != h or int(a) != a:
                continue
            games.append(common | dict(home_score=int(h), away_score=int(a)))
        elif 0 < (start - now).total_seconds() <= 10 * 86400:
            events.append(common)
    return games, events


def capture(output, ref="main", seasons=range(2021, 2027)):
    import pandas as pd

    now = datetime.now(UTC)
    if ref == "main":
        with urllib.request.urlopen(
            "https://api.github.com/repos/sportsdataverse/cfbfastR-cfb-data/commits/main",
            timeout=30,
        ) as r:
            ref = json.load(r)["sha"]

    def get(year):
        url = f"{BASE}{ref}/cfb/cfb_schedules/parquet/cfb_schedules_{year}.parquet"
        with urllib.request.urlopen(url, timeout=30) as r:
            b = r.read(2_000_001)
        if len(b) > 2_000_000:
            raise ValueError("Archive too large")
        data = json.loads(
            pd.read_parquet(io.BytesIO(b)).to_json(orient="records", date_format="iso")
        )
        return data, dict(
            season=year,
            url=url,
            sha256=hashlib.sha256(b).hexdigest(),
            received_at=now.isoformat(),
            bytes=len(b),
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        parts = list(pool.map(get, seasons))
    games, events = normalize([g for records, _ in parts for g in records], now)
    payload = dict(
        provider="sportsdataverse/cfbfastR-cfb-data (CFBD/ESPN derived)",
        sport="americanfootball_ncaaf",
        downloaded_at=now.isoformat(),
        source_commit=ref,
        games=sorted(games, key=lambda x: x["starts_at"]),
        events=events,
        receipts=[receipt for _, receipt in parts],
        commercial_use_permission="UNVERIFIED",
        availability_policy="Retrospective two-day result delay; original receipt times unavailable",
    )
    Path(output).write_text(json.dumps(payload, allow_nan=False) + "\n")
    print(json.dumps(dict(games=len(games), upcoming_events=len(events), source_commit=ref)))
    return payload


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output")
    p.add_argument("--ref", default="main")
    a = p.parse_args()
    capture(a.output, a.ref)


def current_aliases(history, year):
    """Join names by stable provider team ID; never fuzzy-match mascot strings."""
    import pandas as pd

    ref = history["source_commit"]
    url = f"{BASE}{ref}/cfb/schedules/parquet/cfb_schedule_{year}.parquet"
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Alias archive too large")
    canonical = {}
    for game in history["games"] + history["events"]:
        for side in ("home", "away"):
            canonical[game[f"{side}_team_id"]] = game[f"{side}_team"]
    aliases = {}
    for row in json.loads(pd.read_parquet(io.BytesIO(raw)).to_json(orient="records")):
        for side in ("home", "away"):
            key = str(row[f"{side}_id"])
            name = row[f"{side}_team"]
            if key in canonical:
                if name in aliases and aliases[name] != canonical[key]:
                    raise ValueError("Ambiguous team alias")
                aliases[name] = canonical[key]
    return aliases, dict(
        url=url, sha256=hashlib.sha256(raw).hexdigest(), received_at=datetime.now(UTC).isoformat()
    )

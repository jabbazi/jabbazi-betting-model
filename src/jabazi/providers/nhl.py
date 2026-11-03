"""Official NHL schedule adapter; rejects ambiguous final scores and identity conflicts."""

import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from jabazi.models.team_elo import timestamp

SPORT = "icehockey_nhl"
SCHEMA = "nhl-regulation-goals-v1"
# Explicit identities, not fuzzy team-name matching. Arizona and Utah remain distinct.
NAMES = {
    "ANA": "Anaheim Ducks",
    "ARI": "Arizona Coyotes",
    "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",
    "CAR": "Carolina Hurricanes",
    "CBJ": "Columbus Blue Jackets",
    "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",
    "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings",
    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",
    "NJD": "New Jersey Devils",
    "NSH": "Nashville Predators",
    "NYI": "New York Islanders",
    "NYR": "New York Rangers",
    "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins",
    "SEA": "Seattle Kraken",
    "SJS": "San Jose Sharks",
    "STL": "St Louis Blues",
    "TBL": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth",
    "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights",
    "WPG": "Winnipeg Jets",
    "WSH": "Washington Capitals",
}
ALIASES = {
    "St. Louis Blues": "St Louis Blues",
    "Montréal Canadiens": "Montreal Canadiens",
    "Utah Hockey Club": "Utah Mammoth",
}


def canonical(name):
    return ALIASES.get(name, name)


def rows(payloads):
    """Deduplicate club views; preserve postponed/unfinished games as non-results."""
    unique = {}
    ids = {}
    for payload in payloads:
        for g in payload["games"]:
            if g["gameType"] != 2:
                continue
            home, away = g["homeTeam"], g["awayTeam"]
            if home["id"] == away["id"] or home["abbrev"] == away["abbrev"]:
                raise ValueError("NHL home/away identity collision")
            for team in (home, away):
                key = (g["season"], team["abbrev"])
                if key in ids and ids[key] != team["id"]:
                    raise ValueError("NHL team ID changed within season")
                ids[key] = team["id"]
            start = timestamp(g["startTimeUTC"])
            season = int(g["season"])
            if season // 10000 not in (start.year, start.year - 1):
                raise ValueError("NHL season/time mismatch")
            if not str(g["id"]).startswith(str(season // 10000) + "02"):
                raise ValueError("NHL event ID/season/type mismatch")
            if type(g.get("neutralSite")) is not bool:
                raise ValueError("NHL venue context missing")
            row = {
                "game_id": str(g["id"]),
                "season": season,
                "starts_at": start.isoformat(),
                "home_team": NAMES[home["abbrev"]],
                "away_team": NAMES[away["abbrev"]],
                "home_team_id": home["id"],
                "away_team_id": away["id"],
                "neutral_site": g["neutralSite"],
                "game_type": 2,
                "completed": g["gameState"] in {"FINAL", "OFF"},
                "scheduled": g.get("gameScheduleState") == "OK",
            }
            if row["completed"]:
                h, a = home.get("score"), away.get("score")
                period = g.get("gameOutcome", {}).get("lastPeriodType")
                if any(type(x) is not int or not 0 <= x <= 25 for x in (h, a)) or h == a:
                    raise ValueError("NHL final score invalid")
                if period not in {"REG", "OT", "SO"}:
                    raise ValueError("NHL final period missing")
                if period != "REG" and abs(h - a) != 1:
                    raise ValueError("NHL overtime/shootout margin must be one")
                row.update(
                    home_score=h,
                    away_score=a,
                    last_period_type=period,
                    regulation_home=h - int(period != "REG" and h > a),
                    regulation_away=a - int(period != "REG" and a > h),
                    available_at=(start + timedelta(hours=48)).isoformat(),
                )
            key = row["game_id"]
            if key in unique and unique[key] != row:
                raise ValueError("Conflicting NHL duplicate event")
            unique[key] = row
    return sorted(unique.values(), key=lambda r: (r["starts_at"], r["game_id"]))


def fetch_clubs(season, clubs, *, opener=urllib.request.urlopen):
    """Bounded public-feed reads, no credentials and no fallback to synthetic data."""

    def fetch(club):
        if club not in NAMES:
            raise ValueError("Unknown NHL club")
        url = f"https://api-web.nhle.com/v1/club-schedule-season/{club}/{int(season)}"
        request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.3"})
        with opener(request, timeout=25) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("NHL response too large")
        return json.loads(raw), hashlib.sha256(raw).hexdigest()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, sorted(set(clubs))))
    games = rows([r[0] for r in results])
    checksum = hashlib.sha256(json.dumps([r[1] for r in results]).encode()).hexdigest()
    return games, checksum

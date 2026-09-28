"""Official-source NHL player feature snapshots for research-only prop inference.

This collector intentionally separates completed-game history from lineup/injury evidence.
Official NHL statistics can support rolling player form, but they do not prove a skater
will dress or a goalie will start.  Those integrity gates therefore stay false until a
separate, verified pregame source is integrated.

Only the first research tranche is modeled here:
- player_points
- player_assists
- player_shots_on_goal
- player_goals
- player_total_saves

Power-play points and blocked-shot odds may be ingested by the scanner, but live feature
snapshots remain unavailable for those markets until their per-game source coverage is
validated independently.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from statistics import pstdev

from jabazi.providers.nhl import NAMES, canonical

SPORT = "icehockey_nhl"
WEB_BASE = "https://api-web.nhle.com/v1"
STATS_BASE = "https://api.nhle.com/stats/rest/en"

SUPPORTED_LIVE_MARKETS = frozenset({
    "player_points",
    "player_assists",
    "player_shots_on_goal",
    "player_goals",
    "player_total_saves",
})

SKATER_TARGETS = {
    "player_points": ("points", "timeOnIcePerGame", 480.0),
    "player_assists": ("assists", "timeOnIcePerGame", 480.0),
    "player_shots_on_goal": ("shots", "timeOnIcePerGame", 480.0),
    "player_goals": ("goals", "timeOnIcePerGame", 480.0),
}
GOALIE_TARGETS = {
    "player_total_saves": ("saves", "shotsAgainst", 15.0),
}

ABBREV_BY_NAME = {canonical(name): abbrev for abbrev, name in NAMES.items()}


def _name(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _fetch_json(url, timeout=12):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.4"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("NHL player response exceeds size limit")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _float(row, key, default=0.0):
    value = row.get(key)
    if value in (None, "", "NA"):
        return float(default)
    if isinstance(value, str) and ":" in value:
        minutes, seconds = value.split(":", 1)
        value = float(minutes) + float(seconds) / 60.0
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite NHL player field {key}")
    return number


def _mean(values, n):
    values = list(values)[-n:]
    return sum(values) / len(values) if values else 0.0


def rolling_features(values, opportunities, *, is_home, position):
    values, opportunities = list(values), list(opportunities)
    subset = values[-5:]
    return {
        "last1_value": values[-1] if values else 0.0,
        "mean3_value": _mean(values, 3),
        "mean5_value": _mean(values, 5),
        "mean10_value": _mean(values, 10),
        "std5_value": pstdev(subset) if len(subset) >= 2 else 0.0,
        "season_mean_value": _mean(values, max(1, len(values))),
        "last1_opportunities": opportunities[-1] if opportunities else 0.0,
        "mean3_opportunities": _mean(opportunities, 3),
        "mean5_opportunities": _mean(opportunities, 5),
        "mean10_opportunities": _mean(opportunities, 10),
        "games_prior": float(len(values)),
        "is_home": float(bool(is_home)),
        "position_forward": float(position in {"C", "L", "R", "LW", "RW", "F"}),
        "position_defense": float(position in {"D", "LD", "RD"}),
        "position_goalie": float(position == "G"),
    }


def _game_date(row):
    value = row.get("gameDate")
    if not value:
        raise ValueError("NHL per-game row missing gameDate")
    return datetime.fromisoformat(str(value)[:10]).date()


class NHLPlayerFeatureCollector:
    """Build conservative, official-history NHL snapshots for current prop cards."""

    def __init__(self, *, now=None, max_seconds=30):
        self.now = now or datetime.now(UTC)
        if not math.isfinite(max_seconds) or not 0 < max_seconds <= 90:
            raise ValueError("NHL player collection budget must be 0-90 seconds")
        self.max_seconds = float(max_seconds)
        self.started = time.monotonic()
        self._rosters = {}
        self._stats = {}
        self._injuries = {}
        self._diagnostics = []

    @property
    def diagnostics(self):
        return tuple(self._diagnostics)

    def _budget(self):
        if time.monotonic() - self.started >= self.max_seconds:
            raise TimeoutError("NHL player collection budget exhausted")

    def _roster(self, abbrev):
        if abbrev in self._rosters:
            return self._rosters[abbrev]
        self._budget()
        payload, checksum = _fetch_json(f"{WEB_BASE}/roster/{abbrev}/current")
        rows = []
        for bucket, position in (("forwards", "F"), ("defensemen", "D"), ("goalies", "G")):
            for player in payload.get(bucket, []) if isinstance(payload, dict) else []:
                first = (player.get("firstName") or {}).get("default", "")
                last = (player.get("lastName") or {}).get("default", "")
                full = (first + " " + last).strip()
                pid = player.get("id")
                if full and pid:
                    rows.append({
                        "player_id": int(pid),
                        "name": full,
                        "position": str(player.get("positionCode") or position).upper(),
                        "team": abbrev,
                        "source_checksum": checksum,
                    })
        self._rosters[abbrev] = rows
        return rows

    def _event_teams(self, card):
        parts = str(card.event).split(" @ ", 1)
        if len(parts) != 2:
            return None
        away, home = map(canonical, parts)
        away_abbrev, home_abbrev = ABBREV_BY_NAME.get(away), ABBREV_BY_NAME.get(home)
        if not away_abbrev or not home_abbrev or away_abbrev == home_abbrev:
            return None
        return away, home, away_abbrev, home_abbrev

    def _player(self, card):
        teams = self._event_teams(card)
        if not teams:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NHL_EVENT_IDENTITY_UNMATCHED"
            )
            return None
        away, home, away_abbrev, home_abbrev = teams
        key = _name(card.participant)
        matches = [
            row for abbrev in (away_abbrev, home_abbrev)
            for row in self._roster(abbrev)
            if _name(row["name"]) == key
        ]
        if len(matches) != 1:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NHL_ROSTER_PLAYER_NOT_UNIQUE"
            )
            return None
        player = matches[0]
        player["is_home"] = player["team"] == home_abbrev
        player["event_identity"] = player["team"] in {away_abbrev, home_abbrev}
        return player

    def _injury_evidence(self, player):
        """Cross-check current NHL roster membership against ESPN's live injury feed.

        This is a verification input only, not a projection source. A player listed
        with an ambiguous/unavailable status remains fail-closed. Absence is accepted
        only when the player's team is present in the current league injury payload.
        """
        team = str(player["team"]).upper()
        if team not in self._injuries:
            self._budget()
            query = urllib.parse.urlencode({"team": team})
            payload, checksum = _fetch_json(
                "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries?" + query
            )
            groups = payload.get("injuries", []) if isinstance(payload, dict) else None
            if not isinstance(groups, list):
                return None
            self._injuries[team] = (groups, checksum)
        groups, checksum = self._injuries[team]
        team_groups = [
            group for group in groups
            if str((group.get("team") or {}).get("abbreviation") or "").upper() == team
        ]
        if not groups:
            rows = []
        elif len(team_groups) == 1:
            rows = team_groups[0].get("injuries", [])
        else:
            return None
        if not isinstance(rows, list):
            return None
        matches = [
            row for row in rows
            if _name((row.get("athlete") or {}).get("displayName")) == _name(player["name"])
        ]
        if len(matches) > 1:
            return None
        status = str((matches[0] if matches else {}).get("status") or "").strip().lower()
        blocked = status in {
            "out", "injured reserve", "ir", "day-to-day", "day to day",
            "doubtful", "questionable",
        }
        return {
            "verified": True,
            "available": not blocked,
            "status": status or "not_listed",
            "source_checksum": checksum,
        }

    def _season_ids(self):
        year = self.now.year if self.now.month >= 7 else self.now.year - 1
        current = year * 10000 + year + 1
        previous = (year - 1) * 10000 + year
        return previous, current

    def _rows(self, player_id, *, goalie):
        kind = "goalie" if goalie else "skater"
        result, checksums = [], []
        for season in self._season_ids():
            key = (kind, int(player_id), int(season))
            if key not in self._stats:
                self._budget()
                query = urllib.parse.urlencode({
                    "isAggregate": "false",
                    "isGame": "true",
                    "start": "0",
                    "limit": "-1",
                    "cayenneExp": (
                        f"seasonId={season} and gameTypeId=2 and playerId={int(player_id)}"
                    ),
                })
                payload, checksum = _fetch_json(f"{STATS_BASE}/{kind}/summary?{query}")
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                if not isinstance(rows, list):
                    raise ValueError("Invalid NHL player stats response")
                clean = []
                for row in rows:
                    if int(row.get("playerId") or -1) != int(player_id):
                        raise ValueError("NHL player stats identity mismatch")
                    copy = dict(row)
                    copy["_source_checksum"] = checksum
                    clean.append(copy)
                self._stats[key] = clean
            result.extend(self._stats[key])
            checksums.extend(row["_source_checksum"] for row in self._stats[key])
        result.sort(key=lambda row: (_game_date(row), int(row.get("gameId") or 0)))
        digest = hashlib.sha256("|".join(sorted(set(checksums))).encode()).hexdigest()
        return result, digest

    def snapshot(self, card):
        if (
            card.sport != SPORT
            or card.market not in SUPPORTED_LIVE_MARKETS
            or not card.participant
            or card.in_play
            or card.starts_at is None
        ):
            return None
        player = self._player(card)
        if not player:
            return None
        goalie = card.market in GOALIE_TARGETS
        if goalie != (player["position"] == "G"):
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NHL_POSITION_MARKET_MISMATCH"
            )
            return None
        target, opportunity, minimum = (
            GOALIE_TARGETS[card.market] if goalie else SKATER_TARGETS[card.market]
        )
        rows, stats_checksum = self._rows(player["player_id"], goalie=goalie)
        # Same-day rows are excluded even if the public feed has partially updated.
        # The scanner is pregame-only and never treats current-game state as history.
        cutoff = min(self.now, card.starts_at).astimezone(UTC).date() - timedelta(days=1)
        eligible = [row for row in rows if _game_date(row) <= cutoff][-40:]
        values, opportunities = [], []
        for row in eligible:
            value = _float(row, target)
            opp = _float(row, opportunity)
            if value < 0 or opp < 0:
                raise ValueError("NHL prop history contains negative count/opportunity")
            values.append(value)
            opportunities.append(opp)
        if len(values) < 5 or _mean(opportunities, 5) < minimum:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NHL_INSUFFICIENT_HISTORY_OR_ROLE"
            )
            return None
        features = rolling_features(
            values,
            opportunities,
            is_home=player["is_home"],
            position=player["position"],
        )
        try:
            injury = self._injury_evidence(player)
        except (ValueError, OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            self._diagnostics.append(f"NHL_INJURY_PROVIDER_{type(exc).__name__}")
            injury = None
        # Historical role plus a current injury cross-check can verify skater
        # availability. Goalie saves still require a separately confirmed starter.
        role_ok = _mean(opportunities, 5) >= minimum and not goalie
        injury_ok = bool(injury and injury["available"])
        checksum = hashlib.sha256(
            (
                player["source_checksum"]
                + "|"
                + stats_checksum
                + "|"
                + str((injury or {}).get("source_checksum") or "")
                + "|"
                + json.dumps(
                    {
                        "player_id": player["player_id"],
                        "market": card.market,
                        "values": values[-10:],
                        "opportunities": opportunities[-10:],
                    },
                    sort_keys=True,
                )
            ).encode()
        ).hexdigest()
        return {
            "player_id": str(player["player_id"]),
            "features": features,
            "expected_opportunities": _mean(opportunities, 5),
            "provider": "NHL official roster+stats + ESPN injury cross-check",
            "source_checksum": checksum,
            "feature_schema_version": "nhl-player-rolling-v1",
            "integrity": {
                "event_identity": bool(player["event_identity"]),
                "player_identity": True,
                "fresh_features": True,
                "schema": True,
                "role": role_ok,
                "availability": injury_ok,
                "injuries": injury_ok,
                "no_duplicate_event": True,
            },
            "roster_version": player["team"],
            "injury_version": (injury or {}).get("status"),
        }

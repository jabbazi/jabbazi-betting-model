"""Live point-in-time feature collector for NFL, MLB and NHL player props.

Model features are built from completed-game history only. SportsDataIO projections
are used as pregame role/availability evidence, never as the model probability.
All joins are name/date/team checked and fail closed.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from statistics import pstdev
from zoneinfo import ZoneInfo

from jabazi.research.player_features import archive_player_feature_snapshot

def _nfl_stats_url(season):
    return (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"stats_player/stats_player_week_{int(season)}.csv.gz"
    )
NFL_DEPTH = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "depth_charts/depth_charts_2026.csv"
)
NFL_INJURIES = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "injuries/injuries_2026.csv"
)
NFL_TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LV": "Las Vegas Raiders", "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams", "LA": "Los Angeles Rams", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders", "WSH": "Washington Commanders",
}
SPORTSDATA_BASE = "https://api.sportsdata.io/v3"
MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"

NFL_MARKETS = {
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
MLB_MARKETS = {
    "pitcher_strikeouts": ("strikeouts", "batters_faced", 8.0),
    "pitcher_outs": ("outs", "batters_faced", 8.0),
    "pitcher_hits_allowed": ("hits_allowed", "batters_faced", 8.0),
    "pitcher_walks": ("walks_allowed", "batters_faced", 8.0),
    "batter_hits": ("hits", "plate_appearances", 2.0),
    "batter_total_bases": ("total_bases", "plate_appearances", 2.0),
    "batter_home_runs": ("home_run_binary", "plate_appearances", 2.0),
    "batter_rbis": ("rbi", "plate_appearances", 2.0),
    "batter_runs_scored": ("runs", "plate_appearances", 2.0),
    "batter_hits_runs_rbis": ("hrr", "plate_appearances", 2.0),
    "batter_walks": ("walks", "plate_appearances", 2.0),
}


def _name(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _fetch_json(url, timeout=20, *, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.2", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(16_000_001)
        if len(raw) > 16_000_000:
            raise ValueError("Player JSON response exceeds size limit")
        return json.loads(raw)


def _fetch_bytes(url, timeout=30, *, max_bytes=32_000_000):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Player history response exceeds size limit")
        return raw


def _mean(values, n):
    subset = list(values)[-n:]
    return sum(subset) / len(subset) if subset else 0.0


def _base_features(values, opportunities):
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
    }


def _mlb_features(values, opportunities, role):
    result = _base_features(values, opportunities)
    result["mean20_value"] = _mean(values, 20)
    result["role_value"] = float(role)
    return result


def _nfl_features(values, opportunities, position, is_home):
    result = _base_features(values, opportunities)
    result.update(
        is_home=float(is_home),
        position_qb=float(position == "QB"),
        position_rb=float(position == "RB"),
        position_wr=float(position == "WR"),
        position_te=float(position == "TE"),
    )
    return result


def _nfl_granular_context(rows):
    """Research-only documented nflverse weekly metrics; never synthetic-zero missing fields."""
    fields = (
        "passing_air_yards", "passing_epa", "passing_cpoe",
        "receiving_air_yards", "receiving_epa", "target_share",
        "air_yards_share", "wopr", "racr", "rushing_epa",
        "passing_first_downs", "receiving_first_downs", "rushing_first_downs",
    )
    output = {}
    recent = list(rows)[-10:]
    for field in fields:
        values = []
        for row in recent:
            raw = row.get(field)
            if raw in (None, "", "NA"):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
        if values:
            output[f"mean10_{field}"] = sum(values) / len(values)
            output[f"last1_{field}"] = values[-1]
    return output


def _float(row, key, default=0.0):
    value = row.get(key)
    if value in (None, "", "NA"):
        return default
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite {key}")
    return number


def _innings_outs(value):
    if value in (None, ""):
        return 0.0
    text = str(value)
    whole, dot, remainder = text.partition(".")
    if not whole.isdigit() or (dot and remainder not in {"0", "1", "2"}):
        raise ValueError("Invalid innings pitched")
    return float(3 * int(whole) + int(remainder or "0"))


class LivePlayerFeatureCollector:
    def __init__(self, *, sportsdataio_api_key="", now=None, production_verified=None, max_seconds=90):
        self.api_key = sportsdataio_api_key.strip()
        # Operator attestation after verifying the account/feed contract, not a
        # claim inferred from successful HTTP authentication.
        self.production_verified = (
            os.getenv("JABBAZI_SPORTSDATAIO_DATA_MODE", "UNVERIFIED") == "PRODUCTION_VERIFIED"
            if production_verified is None else production_verified is True
        )
        self._last_sportsdata_path = None
        self.now = now or datetime.now(UTC)
        self._nfl_rows = None
        self._nfl_completed = None
        self._nfl_depth_rows = None
        self._nfl_injury_rows = None
        self._nfl_schedule_rows = None
        self._nfl_projection = None
        self._mlb_projection = {}
        self._mlb_people = {}
        self._mlb_logs = {}
        self._mlb_schedule = {}
        self._mlb_live = {}
        self._mlb_active_rosters = {}
        self._nhl_collector = None
        self._nba_collector = None
        self._diagnostics = []
        if not math.isfinite(max_seconds) or not 0 < max_seconds <= 120:
            raise ValueError("Player collection budget must be 0-120 seconds")
        self._max_seconds = float(max_seconds)
        self._collection_elapsed = 0.0

    @property
    def diagnostics(self):
        nhl = self._nhl_collector.diagnostics if self._nhl_collector is not None else ()
        nba = self._nba_collector.diagnostics if self._nba_collector is not None else ()
        return tuple(self._diagnostics) + tuple(nhl) + tuple(nba)


    def provider_status(self):
        result = {
            "configured": bool(self.api_key),
            "production_data_verified": self.production_verified,
            "data_mode": "PRODUCTION_VERIFIED" if self.production_verified else "UNVERIFIED",
            "nfl": {"ok": False, "rows": 0},
            "mlb": {"ok": False, "rows": 0},
            "nhl": {
                "ok": True,
                "provider": "NHL official roster+stats",
                "history_source_verified": True,
                "lineup_injury_source_verified": True,
                "injury_source": "ESPN NHL current injury feed",
                "starting_goalie_source_verified": True,
                "starting_goalie_verification_mode": "ESPN game-level explicit starter flag",
                "note": "Skater injury cross-check is live; goalie saves clear role only when the game-level feed explicitly marks the goalie as starter.",
            },
            "nba": {
                "ok": True,
                "provider": "SportsDataverse ESPN history + ESPN roster/injury verification",
                "history_source_verified": True,
                "lineup_injury_source_verified": True,
                "starting_lineup_required": False,
                "note": "Current model role gate uses active roster, injury clearance, and recent rotation minutes; announced starting-five status is not a model input.",
            },
        }
        result["nfl"]["fallback"] = {
            "history": "nflverse weekly player stats",
            "role": "nflverse depth charts",
            "injuries": "nflverse weekly injury reports",
            "production_projection_required": False,
        }
        result["mlb"]["fallback"] = {
            "history": "MLB StatsAPI game logs",
            "role": "MLB StatsAPI posted batting order/probable pitcher",
            "production_projection_required": False,
        }
        if not self.api_key:
            return result
        try:
            season = self._sportsdata("nfl/scores/json/CurrentSeason")
            week = self._sportsdata("nfl/scores/json/CurrentWeek")
            if isinstance(season, dict):
                season = season.get("Season") or season.get("season")
            if isinstance(week, dict):
                week = week.get("Week") or week.get("week")
            rows = self._sportsdata(
                f"nfl/projections/json/PlayerGameProjectionStatsByWeek/{int(season)}/{int(week)}"
            )
            result["nfl"].update({
                "ok": isinstance(rows, list) and len(rows) > 0,
                "rows": len(rows) if isinstance(rows, list) else 0,
                "season": int(season),
                "week": int(week),
            })
        except urllib.error.HTTPError as exc:
            result["nfl"].update(self._provider_failure(exc.code))
        except (ValueError, TypeError, OSError, urllib.error.URLError) as exc:
            result["nfl"].update({"ok": False, "rows": 0, "error": type(exc).__name__})

        try:
            local_date = self.now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            rows = self._sportsdata(
                f"mlb/projections/json/PlayerGameProjectionStatsByDate/{local_date}"
            )
            result["mlb"].update({
                "ok": isinstance(rows, list) and len(rows) > 0,
                "rows": len(rows) if isinstance(rows, list) else 0,
                "date": local_date,
            })
        except urllib.error.HTTPError as exc:
            result["mlb"].update(self._provider_failure(exc.code))
        except (ValueError, TypeError, OSError, urllib.error.URLError) as exc:
            result["mlb"].update({"ok": False, "rows": 0, "error": type(exc).__name__})
        return result

    def _provider_failure(self, status):
        return {
            "ok": False, "rows": 0, "error": f"HTTP_{status}",
            "endpoint": self._last_sportsdata_path,
            "action_required": (
                "Verify the SportsDataIO key and access to this sport/feed; do not substitute trial data"
                if status in (401, 403) else "Investigate provider availability before retrying"
            ),
        }

    def _sportsdata(self, path):
        if not self.api_key:
            return None
        self._last_sportsdata_path = path
        return _fetch_json(
            f"{SPORTSDATA_BASE}/{path}",
            headers={"Ocp-Apim-Subscription-Key": self.api_key},
        )

    def _nfl_history(self):
        if self._nfl_rows is not None:
            return self._nfl_rows
        # A failed feed is retried on the next scan, never once per player.
        self._nfl_rows = []
        rows = []
        digest = hashlib.sha256()
        seasons = (self.now.year - 1, self.now.year)
        for season in seasons:
            raw = _fetch_bytes(_nfl_stats_url(season))
            digest.update(hashlib.sha256(raw).hexdigest().encode())
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
                with io.TextIOWrapper(zipped, encoding="utf-8") as source:
                    reader = csv.DictReader(source)
                    required = {
                        "player_id", "player_display_name", "position", "season", "week",
                        "season_type", "game_id", "team", "completions", "attempts",
                        "passing_yards", "passing_tds", "carries", "rushing_yards",
                        "rushing_tds", "receptions", "targets", "receiving_yards",
                        "receiving_tds",
                    }
                    if not required <= set(reader.fieldnames or []):
                        raise ValueError("nflverse current player schema mismatch")
                    for row in reader:
                        if row.get("season_type") != "REG" or int(row["season"]) != season:
                            continue
                        rows.append(dict(row))
        checksum = digest.hexdigest()
        for row in rows:
            row["_source_checksum"] = checksum
        self._nfl_rows = rows
        return rows

    def _nfl_depth_charts(self):
        if self._nfl_depth_rows is not None:
            return self._nfl_depth_rows
        self._nfl_depth_rows = []
        raw = _fetch_bytes(NFL_DEPTH.replace("2026.csv", f"{self.now.year if self.now.month >= 7 else self.now.year - 1}.csv"))
        checksum = hashlib.sha256(raw).hexdigest()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        required = {"dt", "team", "player_name", "gsis_id", "pos_abb", "pos_rank"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("nflverse current depth-chart schema mismatch")
        rows = []
        for row in reader:
            row = dict(row)
            row["_source_checksum"] = checksum
            rows.append(row)
        self._nfl_depth_rows = rows
        return rows

    def _nfl_depth_for(self, participant):
        key = _name(participant)
        matches = [
            row for row in self._nfl_depth_charts()
            if _name(row.get("player_name")) == key
        ]
        if not matches:
            return None
        def stamp(row):
            try:
                value = datetime.fromisoformat(str(row.get("dt")).replace("Z", "+00:00"))
                return value if value.tzinfo else value.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                return datetime.min.replace(tzinfo=UTC)
        return max(matches, key=stamp)

    def _nfl_event_role(self, card, depth, fallback_team):
        team = str((depth or {}).get("team") or fallback_team or "").upper()
        team_name = NFL_TEAM_NAMES.get(team)
        sides = tuple(part.strip() for part in str(card.event).split(" @ ", 1))
        if len(sides) != 2 or not team_name or team_name not in sides:
            return team, None, False
        is_home = team_name == sides[1]
        return team, is_home, True

    def _nfl_schedule(self):
        if self._nfl_schedule_rows is not None:
            return self._nfl_schedule_rows
        raw = _fetch_bytes(
            "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
        )
        reader = csv.DictReader(io.StringIO(raw.decode()))
        rows = []
        season = self.now.year if self.now.month >= 7 else self.now.year - 1
        for row in reader:
            if int(row.get("season") or 0) != season or row.get("game_type") != "REG":
                continue
            if not row.get("gameday") or not row.get("gametime"):
                continue
            try:
                start = (
                    datetime.fromisoformat(row["gameday"] + "T" + row["gametime"])
                    .replace(tzinfo=ZoneInfo("America/New_York"))
                    .astimezone(UTC)
                )
            except ValueError:
                continue
            rows.append({
                "week": int(row["week"]),
                "start": start,
                "home": NFL_TEAM_NAMES.get(row.get("home_team")),
                "away": NFL_TEAM_NAMES.get(row.get("away_team")),
                "home_abbr": row.get("home_team"),
                "away_abbr": row.get("away_team"),
            })
        self._nfl_schedule_rows = rows
        return rows

    def _nfl_card_context(self, card):
        parts = str(getattr(card, "event", "") or "").split(" @ ", 1)
        if len(parts) != 2:
            return None
        away, home = parts
        matches = [
            row for row in self._nfl_schedule()
            if row["away"] == away
            and row["home"] == home
            and abs((row["start"] - card.starts_at.astimezone(UTC)).total_seconds()) <= 3 * 3600
        ]
        return matches[0] if len(matches) == 1 else None

    def _nfl_injuries(self):
        if self._nfl_injury_rows is not None:
            return self._nfl_injury_rows
        season = self.now.year if self.now.month >= 7 else self.now.year - 1
        url = NFL_INJURIES.replace("2026.csv", f"{season}.csv")
        raw = _fetch_bytes(url)
        checksum = hashlib.sha256(raw).hexdigest()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        required = {"season", "team", "week", "gsis_id", "full_name", "report_status", "date_modified"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("nflverse injury-report schema mismatch")
        rows = []
        for row in reader:
            if int(row.get("season") or 0) != season:
                continue
            copy = dict(row)
            copy["_source_checksum"] = checksum
            rows.append(copy)
        self._nfl_injury_rows = rows
        return rows

    def _nfl_injury_evidence(self, card, participant, depth):
        try:
            context = self._nfl_card_context(card)
            injury_rows = self._nfl_injuries()
        except (ValueError, OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            self._diagnostics.append(f"NFLVERSE_INJURY_PROVIDER_{type(exc).__name__}")
            return None
        if not context:
            return None
        team = str((depth or {}).get("team") or "").upper()
        if team not in {context["home_abbr"], context["away_abbr"]}:
            return None
        rows = [
            row for row in injury_rows
            if str(row.get("team") or "").upper() == team
            and int(row.get("week") or -1) == context["week"]
        ]
        if not rows:
            return None

        def modified(row):
            try:
                value = datetime.fromisoformat(str(row.get("date_modified")).replace("Z", "+00:00"))
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                return value.astimezone(UTC)
            except (TypeError, ValueError):
                return datetime.min.replace(tzinfo=UTC)

        latest_team = max(modified(row) for row in rows)
        if latest_team > self.now or (self.now - latest_team).total_seconds() > 96 * 3600:
            return None
        gsis = str((depth or {}).get("gsis_id") or "")
        matches = [
            row for row in rows
            if (gsis and str(row.get("gsis_id") or "") == gsis)
            or _name(row.get("full_name")) == _name(participant)
        ]
        row = max(matches, key=modified) if matches else None
        status = str((row or {}).get("report_status") or "").strip().lower()
        unavailable = status in {
            "out", "doubtful", "questionable", "inactive", "injured reserve"
        }
        return {
            "verified": True,
            "status": status or "not_listed",
            "available_by_injury_report": not unavailable,
            "modified_at": latest_team.isoformat(),
            "source_checksum": rows[0]["_source_checksum"],
            "week": context["week"],
        }

    def _nfl_projections(self):
        if self._nfl_projection is not None:
            return self._nfl_projection
        # Cache failure as an empty feed for this scan. Without this sentinel, one
        # provider error is retried once per player card and can stall a full scan.
        self._nfl_projection = []
        if not self.production_verified:
            self._diagnostics.append("SPORTSDATA_NFL_UNVERIFIED_DATA_QUARANTINED")
            return self._nfl_projection
        if not self.api_key:
            return self._nfl_projection
        try:
            season = self._sportsdata("nfl/scores/json/CurrentSeason")
            week = self._sportsdata("nfl/scores/json/CurrentWeek")
            if isinstance(season, dict):
                season = season.get("Season") or season.get("season")
            if isinstance(week, dict):
                week = week.get("Week") or week.get("week")
            rows = self._sportsdata(
                f"nfl/projections/json/PlayerGameProjectionStatsByWeek/{int(season)}/{int(week)}"
            ) or []
            self._nfl_projection = rows if isinstance(rows, list) else []
        except urllib.error.HTTPError as exc:
            self._diagnostics.append(f"SPORTSDATA_NFL_PROVIDER_HTTP_{exc.code}")
        except (ValueError, TypeError, OSError, urllib.error.URLError) as exc:
            self._diagnostics.append(f"SPORTSDATA_NFL_PROVIDER_{type(exc).__name__}")
        return self._nfl_projection

    def _projection_time_matches(self, value, starts_at, *, eastern=False):
        if not value or starts_at is None:
            return False
        try:
            raw = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=ZoneInfo("America/New_York") if eastern else UTC
                )
            parsed = parsed.astimezone(UTC)
            return abs((parsed - starts_at.astimezone(UTC)).total_seconds()) <= 3 * 3600
        except (ValueError, TypeError):
            return False

    def _nfl_projection_for(self, participant, starts_at):
        key = _name(participant)
        matches = [
            row for row in self._nfl_projections()
            if _name(row.get("Name")) == key
            and self._projection_time_matches(row.get("GameDate"), starts_at, eastern=True)
        ]
        return matches[0] if len(matches) == 1 else None

    def _nfl_available_games(self):
        if self._nfl_completed is None:
            self._nfl_completed = {}
            from jabazi.providers.history import nfl_rows
            raw = _fetch_bytes("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv")
            games = nfl_rows(raw.decode(), {self.now.year - 1, self.now.year})
            self._nfl_completed = {
                g["game_id"]: datetime.fromisoformat(g["starts_at"]) + timedelta(days=2)
                for g in games
            }
        return self._nfl_completed

    def nfl_snapshot(self, card):
        market = NFL_MARKETS.get(card.market)
        if not market or not card.participant:
            return None
        target, opportunity, minimum = market
        if card.starts_at is None:
            return None
        available_games = self._nfl_available_games()
        cutoff = min(self.now, card.starts_at)
        player_rows = [
            row for row in self._nfl_history()
            if _name(row.get("player_display_name")) == _name(card.participant)
            and row.get("game_id") in available_games
            and available_games[row["game_id"]] < cutoff
        ]
        if not player_rows:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NFL_HISTORY_PLAYER_NOT_FOUND"
            )
            return None
        player_rows.sort(key=lambda r: (int(r["season"]), int(r["week"]), r["game_id"]))
        player_rows = player_rows[-32:]
        values, opportunities = [], []
        for row in player_rows:
            rushing_tds = _float(row, "rushing_tds")
            receiving_tds = _float(row, "receiving_tds")
            derived = {
                "anytime_td": float(rushing_tds + receiving_tds > 0),
                "touch_opportunities": _float(row, "carries") + _float(row, "targets"),
            }
            values.append(derived[target] if target in derived else _float(row, target))
            opportunities.append(
                derived[opportunity] if opportunity in derived else _float(row, opportunity)
            )
        if len(values) < 3 or _mean(opportunities, 3) < minimum:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NFL_INSUFFICIENT_HISTORY_OR_ROLE"
            )
            return None

        projection = self._nfl_projection_for(card.participant, card.starts_at)
        depth = self._nfl_depth_for(card.participant)
        injury_evidence = self._nfl_injury_evidence(card, card.participant, depth)
        if projection is None:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:SPORTSDATA_NFL_PROJECTION_NOT_MATCHED"
            )
        if depth is None:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NFLVERSE_DEPTH_PLAYER_NOT_FOUND"
            )
        position = str(
            (projection or {}).get("Position")
            or (depth or {}).get("pos_abb")
            or player_rows[-1].get("position")
            or ""
        ).upper()
        team, fallback_is_home, event_identity = self._nfl_event_role(
            card, depth, player_rows[-1].get("team")
        )
        homeaway = str((projection or {}).get("HomeOrAway") or "").lower()
        if homeaway in {"home", "away"}:
            is_home = homeaway == "home"
            event_identity = True
        elif fallback_is_home is not None:
            is_home = fallback_is_home
        else:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NFL_EVENT_TEAM_NOT_MATCHED"
            )
            return None
        injury = str((projection or {}).get("InjuryStatus") or "").strip().lower()
        active = (
            projection is not None
            and int((projection or {}).get("Activated") or 0) == 1
            and int((projection or {}).get("Played") or 0) == 1
            and injury not in {
                "out", "doubtful", "questionable", "inactive", "injured reserve"
            }
        )
        injury_ok = (
            active if projection is not None
            else bool(injury_evidence and injury_evidence["available_by_injury_report"])
        )
        depth_rank = _float(depth or {}, "pos_rank", 99.0)
        depth_role = depth is not None and depth_rank <= 2.0
        projected_opportunities = {
            "player_pass_yds": _float(projection or {}, "PassingAttempts", _mean(opportunities, 3)),
            "player_pass_attempts": _float(projection or {}, "PassingAttempts", _mean(opportunities, 3)),
            "player_pass_completions": _float(projection or {}, "PassingAttempts", _mean(opportunities, 3)),
            "player_pass_tds": _float(projection or {}, "PassingAttempts", _mean(opportunities, 3)),
            "player_rush_yds": _float(projection or {}, "RushingAttempts", _mean(opportunities, 3)),
            "player_rush_attempts": _float(projection or {}, "RushingAttempts", _mean(opportunities, 3)),
            "player_receptions": _float(projection or {}, "ReceivingTargets", _mean(opportunities, 3)),
            "player_reception_yds": _float(projection or {}, "ReceivingTargets", _mean(opportunities, 3)),
            "player_anytime_td": (
                _float(projection or {}, "RushingAttempts", 0)
                + _float(projection or {}, "ReceivingTargets", 0)
            ) or _mean(opportunities, 3),
        }[card.market]
        features = _nfl_features(values, opportunities, position, is_home)
        depth_checksum = str((depth or {}).get("_source_checksum") or "")
        injury_checksum = str((injury_evidence or {}).get("source_checksum") or "")
        source_checksum = hashlib.sha256(
            (
                player_rows[-1]["_source_checksum"]
                + "|"
                + depth_checksum
                + "|"
                + injury_checksum
                + "|"
                + json.dumps(projection or {}, sort_keys=True, allow_nan=False)
            ).encode()
        ).hexdigest()
        return {
            "player_id": str(
                (projection or {}).get("PlayerID")
                or (depth or {}).get("gsis_id")
                or player_rows[-1]["player_id"]
            ),
            "features": features,
            "expected_opportunities": projected_opportunities,
            "provider": (
                "nflverse-history+depth-chart+SportsDataIO"
                if projection else "nflverse-history+depth-chart"
            ),
            "source_checksum": source_checksum,
            "feature_schema_version": "nfl-player-rolling-v1",
            "integrity": {
                "event_identity": event_identity,
                "player_identity": depth is not None,
                "fresh_features": True,
                "schema": True,
                "role": projected_opportunities >= minimum and (depth_role or projection is not None),
                # A current team injury report plus a current depth-chart identity
                # verifies pregame availability only for players who are not listed
                # questionable/doubtful/out/inactive/IR. Ambiguous statuses stay closed.
                "availability": active if projection is not None else injury_ok,
                "injuries": injury_ok,
                "no_duplicate_event": event_identity,
            },
            "roster_version": str((projection or {}).get("Team") or team or ""),
            "injury_version": injury or (injury_evidence or {}).get("modified_at"),
            "research_context": _nfl_granular_context(player_rows),
            "research_context_provider": "nflverse weekly player stats",
            "research_context_schema": "nfl-granular-weekly-v1",
        }

    def _mlb_projections(self, starts_at):
        local_date = starts_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if local_date in self._mlb_projection:
            return self._mlb_projection[local_date]
        # Same fail-fast rule as NFL: one provider failure per date, not per player.
        self._mlb_projection[local_date] = []
        if not self.production_verified:
            self._diagnostics.append("SPORTSDATA_MLB_UNVERIFIED_DATA_QUARANTINED")
            return self._mlb_projection[local_date]
        if not self.api_key:
            return self._mlb_projection[local_date]
        try:
            rows = self._sportsdata(
                f"mlb/projections/json/PlayerGameProjectionStatsByDate/{local_date}"
            ) or []
            self._mlb_projection[local_date] = rows if isinstance(rows, list) else []
        except urllib.error.HTTPError as exc:
            self._diagnostics.append(
                f"SPORTSDATA_MLB_PROVIDER_HTTP_{exc.code}:{local_date}"
            )
        except (ValueError, TypeError, OSError, urllib.error.URLError) as exc:
            self._diagnostics.append(
                f"SPORTSDATA_MLB_PROVIDER_{type(exc).__name__}:{local_date}"
            )
        return self._mlb_projection[local_date]

    def _mlb_projection_for(self, participant, starts_at):
        key = _name(participant)
        rows = [
            r for r in self._mlb_projections(starts_at)
            if _name(r.get("Name")) == key
            and self._projection_time_matches(r.get("DateTime"), starts_at, eastern=True)
        ]
        return rows[0] if len(rows) == 1 else None

    def _mlb_person(self, participant):
        key = _name(participant)
        if key in self._mlb_people:
            return self._mlb_people[key]
        self._mlb_people[key] = None
        query = urllib.parse.urlencode(
            {"names": participant, "sportIds": 1, "active": "true"}
        )
        payload = _fetch_json(f"{MLB_STATS_BASE}/people/search?{query}")
        people = payload.get("people", []) if isinstance(payload, dict) else []
        exact = [p for p in people if _name(p.get("fullName")) == key]
        self._mlb_people[key] = exact[0] if len(exact) == 1 else None
        return self._mlb_people[key]

    def _mlb_game_logs(self, participant, group):
        person = self._mlb_person(participant)
        if not person:
            return []
        key = (person["id"], group, self.now.year)
        if key in self._mlb_logs:
            return self._mlb_logs[key]
        self._mlb_logs[key] = []
        query = urllib.parse.urlencode(
            {"stats": "gameLog", "group": group, "season": self.now.year}
        )
        payload = _fetch_json(
            f"{MLB_STATS_BASE}/people/{person['id']}/stats?{query}"
        )
        splits = []
        for stat_group in payload.get("stats", []) if isinstance(payload, dict) else []:
            splits.extend(stat_group.get("splits", []))
        self._mlb_logs[key] = splits
        return splits

    def _mlb_event_context(self, card):
        """Resolve one Odds API event to an official MLB game and posted role evidence."""
        local_date = card.starts_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if local_date not in self._mlb_schedule:
            query = urllib.parse.urlencode({
                "sportId": 1,
                "date": local_date,
                "hydrate": "probablePitcher",
            })
            payload = _fetch_json(f"{MLB_STATS_BASE}/schedule?{query}")
            games = []
            for date in payload.get("dates", []) if isinstance(payload, dict) else []:
                games.extend(date.get("games", []))
            self._mlb_schedule[local_date] = games

        from jabazi.providers.history import MLB_ALIASES
        parts = str(getattr(card, "event", "") or "").split(" @ ", 1)
        if len(parts) != 2:
            return None
        away, home = [MLB_ALIASES.get(part.strip(), part.strip()) for part in parts]
        matches = []
        for game in self._mlb_schedule[local_date]:
            try:
                game_away = MLB_ALIASES.get(game["teams"]["away"]["team"]["name"], game["teams"]["away"]["team"]["name"])
                game_home = MLB_ALIASES.get(game["teams"]["home"]["team"]["name"], game["teams"]["home"]["team"]["name"])
                start = datetime.fromisoformat(str(game["gameDate"]).replace("Z", "+00:00")).astimezone(UTC)
                if (
                    game_away == away
                    and game_home == home
                    and abs((start - card.starts_at.astimezone(UTC)).total_seconds()) <= 3 * 3600
                ):
                    matches.append(game)
            except (KeyError, TypeError, ValueError):
                continue
        if len(matches) != 1:
            return None
        game = matches[0]
        game_pk = int(game["gamePk"])
        if game_pk not in self._mlb_live:
            try:
                self._mlb_live[game_pk] = _fetch_json(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live")
            except (ValueError, OSError, urllib.error.URLError, urllib.error.HTTPError):
                self._mlb_live[game_pk] = {}
        return game, self._mlb_live[game_pk]

    def _mlb_active_roster_has(self, team_id, person_id, date):
        key = (int(team_id), str(date))
        if key not in self._mlb_active_rosters:
            query = urllib.parse.urlencode({
                "rosterType": "active",
                "date": str(date),
            })
            payload = _fetch_json(f"{MLB_STATS_BASE}/teams/{int(team_id)}/roster?{query}")
            roster = payload.get("roster", []) if isinstance(payload, dict) else []
            if not isinstance(roster, list):
                return False
            self._mlb_active_rosters[key] = {
                int((row.get("person") or {}).get("id"))
                for row in roster
                if (row.get("person") or {}).get("id") is not None
            }
        return int(person_id) in self._mlb_active_rosters[key]

    def _mlb_official_role(self, card, person, pitcher):
        context = self._mlb_event_context(card)
        if not context or not person:
            return None
        game, live = context
        pid = int(person["id"])
        sides = ("away", "home")
        participant_side = None
        for side in sides:
            team = (live.get("gameData", {}).get("teams", {}).get(side, {}) or {}).get("name")
            if team and team in str(card.event):
                roster = (
                    live.get("liveData", {}).get("boxscore", {}).get("teams", {}).get(side, {})
                )
                players = roster.get("players", {}) if isinstance(roster, dict) else {}
                if f"ID{pid}" in players:
                    participant_side = side
                    break
        local_date = card.starts_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if pitcher:
            probable_side = next(
                (
                    side for side in sides
                    if (game.get("teams", {}).get(side, {}).get("probablePitcher") or {}).get("id")
                    == pid
                ),
                None,
            )
            confirmed = probable_side is not None
            team_id = (
                (game.get("teams", {}).get(probable_side, {}).get("team") or {}).get("id")
                if probable_side else None
            )
            active_roster = bool(
                confirmed and team_id
                and self._mlb_active_roster_has(team_id, pid, local_date)
            )
            return {
                "role": 1.0 if confirmed else 0.0,
                "role_ok": confirmed and active_roster,
                "active_roster": active_roster,
                "event_identity": confirmed or participant_side is not None,
                "team": probable_side or participant_side,
                "source": "MLB StatsAPI probablePitcher+active roster",
            }
        if participant_side is None:
            return None
        box = live.get("liveData", {}).get("boxscore", {}).get("teams", {}).get(participant_side, {})
        order = [int(value) for value in box.get("battingOrder", []) if str(value).isdigit()]
        confirmed = pid in order
        team_id = (game.get("teams", {}).get(participant_side, {}).get("team") or {}).get("id")
        active_roster = bool(
            confirmed and team_id and self._mlb_active_roster_has(team_id, pid, local_date)
        )
        return {
            "role": float(order.index(pid) + 1) if confirmed else 0.0,
            "role_ok": confirmed and active_roster,
            "active_roster": active_roster,
            "event_identity": True,
            "team": participant_side,
            "source": "MLB StatsAPI posted battingOrder+active roster",
        }

    def mlb_snapshot(self, card):
        market = MLB_MARKETS.get(card.market)
        if not market or not card.participant or card.starts_at is None:
            return None
        target, opportunity, minimum = market
        pitcher = card.market.startswith("pitcher_")
        logs = self._mlb_game_logs(card.participant, "pitching" if pitcher else "hitting")
        values, opportunities = [], []
        # Conservative availability proxy: no same-day or yesterday results.
        # Historical receipt timestamps are unavailable from this endpoint.
        cutoff = min(self.now, card.starts_at).astimezone(UTC).date() - timedelta(days=2)
        eligible = []
        seen_games = set()
        for split in logs:
            try:
                date = datetime.strptime(str(split.get("date")), "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            game_id = (split.get("game") or {}).get("gamePk")
            if date > cutoff or not game_id or game_id in seen_games:
                continue
            seen_games.add(game_id)
            eligible.append(split)
        for split in sorted(eligible, key=lambda row: (row["date"], row["game"]["gamePk"])):
            stat = split.get("stat", {})
            if pitcher:
                derived = {
                    "strikeouts": _float(stat, "strikeOuts"),
                    "outs": _innings_outs(stat.get("inningsPitched")),
                    "hits_allowed": _float(stat, "hits"),
                    "walks_allowed": _float(stat, "baseOnBalls"),
                    "batters_faced": _float(stat, "battersFaced"),
                }
            else:
                hits = _float(stat, "hits")
                doubles = _float(stat, "doubles")
                triples = _float(stat, "triples")
                homers = _float(stat, "homeRuns")
                singles = max(0.0, hits-doubles-triples-homers)
                runs, rbi = _float(stat, "runs"), _float(stat, "rbi")
                derived = {
                    "hits": hits,
                    "total_bases": singles + 2*doubles + 3*triples + 4*homers,
                    "home_run_binary": float(homers > 0),
                    "rbi": rbi,
                    "runs": runs,
                    "hrr": hits + runs + rbi,
                    "walks": _float(stat, "baseOnBalls"),
                    "plate_appearances": _float(stat, "plateAppearances"),
                }
            if target in derived and opportunity in derived and derived[opportunity] > 0:
                values.append(derived[target])
                opportunities.append(derived[opportunity])
        if len(values) < 5 or _mean(opportunities, 5) < minimum:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:MLB_INSUFFICIENT_HISTORY_OR_ROLE"
            )
            return None

        projection = self._mlb_projection_for(card.participant, card.starts_at)
        person = self._mlb_person(card.participant)
        official = self._mlb_official_role(card, person, pitcher)
        if not projection:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:SPORTSDATA_MLB_PROJECTION_NOT_MATCHED"
            )
        injury = str((projection or {}).get("InjuryStatus") or "").strip().lower()
        active = bool(projection) and injury not in {"out", "doubtful", "injured list"}
        if projection:
            if pitcher:
                role = 1.0 if int(projection.get("Started") or 0) == 1 else 0.0
                role_ok = role == 1.0 and bool(projection.get("BattingOrderConfirmed"))
                projected_opps = _mean(opportunities, 5)
            else:
                role = float(projection.get("BattingOrder") or 0)
                role_ok = role >= 1 and bool(projection.get("BattingOrderConfirmed"))
                projected_opps = _float(projection, "PlateAppearances", _mean(opportunities, 5))
            event_identity = True
            role_source = "SportsDataIO projection"
        elif official:
            role = official["role"]
            role_ok = official["role_ok"]
            projected_opps = _mean(opportunities, 5)
            event_identity = official["event_identity"]
            role_source = official["source"]
        else:
            role = 0.0
            role_ok = False
            projected_opps = _mean(opportunities, 5)
            event_identity = False
            role_source = "unverified"
        features = _mlb_features(values, opportunities, role)
        checksum = hashlib.sha256(
            json.dumps(
                {
                    "person": person.get("id") if person else None,
                    "last": values[-20:],
                    "projection": {
                        key: (projection or {}).get(key)
                        for key in (
                            "PlayerID", "Team", "Position", "InjuryStatus", "Started",
                            "BattingOrder", "BattingOrderConfirmed",
                        )
                    },
                    "official_role": official,
                    "role_source": role_source,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return {
            "player_id": str((projection or {}).get("PlayerID") or (person or {}).get("id") or ""),
            "features": features,
            "expected_opportunities": projected_opps,
            "provider": (
                "MLB StatsAPI+SportsDataIO"
                if projection
                else "MLB StatsAPI official history+schedule/role"
            ),
            "source_checksum": checksum,
            "feature_schema_version": "mlb-player-rolling-v1",
            "integrity": {
                "event_identity": event_identity,
                "player_identity": person is not None,
                "fresh_features": True,
                "schema": True,
                "role": role_ok and projected_opps >= minimum,
                "availability": active if projection else bool(official and official["role_ok"]),
                "injuries": (
                    active
                    if projection
                    else bool(official and official.get("active_roster") and official["role_ok"])
                ),
                "no_duplicate_event": event_identity,
            },
            "roster_version": str((projection or {}).get("Team") or (official or {}).get("team") or ""),
            "injury_version": injury or None,
        }

    def sync(self, store, cards):
        """Archive one evidence snapshot per unique prop participant/event/market."""
        seen = set()
        archived = 0
        started = time.monotonic()
        for card in cards:
            if self._collection_elapsed + time.monotonic() - started >= self._max_seconds:
                self._diagnostics.append("PLAYER_FEATURE_BUDGET_EXHAUSTED")
                break
            if not card.participant or card.in_play:
                continue
            key = (card.sport, card.event_id, card.participant, card.market)
            if key in seen:
                continue
            seen.add(key)
            try:
                if card.sport == "americanfootball_nfl":
                    payload = self.nfl_snapshot(card)
                elif card.sport == "baseball_mlb":
                    payload = self.mlb_snapshot(card)
                elif card.sport == "icehockey_nhl":
                    if self._nhl_collector is None:
                        from jabazi.providers.nhl_player_features import NHLPlayerFeatureCollector
                        remaining = max(
                            1.0,
                            min(
                                30.0,
                                self._max_seconds
                                - self._collection_elapsed
                                - (time.monotonic() - started),
                            ),
                        )
                        self._nhl_collector = NHLPlayerFeatureCollector(
                            now=self.now, max_seconds=remaining
                        )
                    payload = self._nhl_collector.snapshot(card)
                elif card.sport == "basketball_nba":
                    if self._nba_collector is None:
                        from jabazi.providers.nba_player_features import NBAPlayerFeatureCollector
                        self._nba_collector = NBAPlayerFeatureCollector(now=self.now)
                    payload = self._nba_collector.snapshot(card)
                else:
                    payload = None
                if not payload:
                    continue
                research_only = not all(payload["integrity"].values())
                if research_only:
                    failed = ",".join(
                        key for key, value in payload["integrity"].items() if value is not True
                    )
                    self._diagnostics.append(
                        f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:RESEARCH_ONLY_PLAYER_INPUTS:{failed}"
                    )
                archived += bool(
                    archive_player_feature_snapshot(
                        store,
                        sport=card.sport,
                        event_id=card.event_id,
                        participant=card.participant,
                        market=card.market,
                        player_id=payload["player_id"],
                        starts_at=card.starts_at.isoformat(),
                        features_available_at=self.now.isoformat(),
                        features=payload["features"],
                        expected_opportunities=payload["expected_opportunities"],
                        integrity=payload["integrity"],
                        provider=payload["provider"],
                        source_checksum=payload["source_checksum"],
                        feature_schema_version=payload["feature_schema_version"],
                        roster_version=payload["roster_version"],
                        injury_version=payload["injury_version"],
                        research_only=research_only,
                        provider_data_verified=(self.production_verified if "SportsDataIO" in payload["provider"] else None),
                    )
                )
                if payload.get("research_context"):
                    from jabazi.research.granular import archive_granular_snapshot
                    archive_granular_snapshot(
                        store,
                        sport=card.sport,
                        event_id=card.event_id,
                        participant=card.participant,
                        starts_at=card.starts_at.isoformat(),
                        available_at=self.now.isoformat(),
                        features=payload["research_context"],
                        provider=payload.get("research_context_provider") or payload["provider"],
                        source_checksum=payload["source_checksum"],
                        schema_version=payload.get("research_context_schema") or "granular-v1",
                    )
            except (ValueError, KeyError, TypeError, OSError, urllib.error.URLError) as exc:
                self._diagnostics.append(
                    f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:{type(exc).__name__}"
                )
        self._collection_elapsed += time.monotonic() - started
        return archived

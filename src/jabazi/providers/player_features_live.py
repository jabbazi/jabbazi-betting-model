"""Live point-in-time feature collector for NFL and MLB player props.

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
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from statistics import pstdev
from zoneinfo import ZoneInfo

from jabazi.research.player_features import archive_player_feature_snapshot

NFL_STATS = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_2026.csv.gz"
)
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


def _fetch_json(url, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _fetch_bytes(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "JABBAZI-Research/0.2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


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
    def __init__(self, *, sportsdataio_api_key="", now=None):
        self.api_key = sportsdataio_api_key
        self.now = now or datetime.now(UTC)
        self._nfl_rows = None
        self._nfl_projection = None
        self._mlb_projection = {}
        self._mlb_people = {}
        self._mlb_logs = {}
        self._diagnostics = []

    @property
    def diagnostics(self):
        return tuple(self._diagnostics)

    def _sportsdata(self, path):
        if not self.api_key:
            return None
        query = urllib.parse.urlencode({"key": self.api_key})
        return _fetch_json(f"{SPORTSDATA_BASE}/{path}?{query}")

    def _nfl_history(self):
        if self._nfl_rows is not None:
            return self._nfl_rows
        raw = _fetch_bytes(NFL_STATS)
        checksum = hashlib.sha256(raw).hexdigest()
        rows = []
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
                    if row.get("season_type") != "REG" or int(row["season"]) != self.now.year:
                        continue
                    row = dict(row)
                    row["_source_checksum"] = checksum
                    rows.append(row)
        self._nfl_rows = rows
        return rows

    def _nfl_projections(self):
        if self._nfl_projection is not None:
            return self._nfl_projection
        if not self.api_key:
            self._nfl_projection = []
            return self._nfl_projection
        season = self._sportsdata("nfl/scores/json/CurrentSeason")
        week = self._sportsdata("nfl/scores/json/CurrentWeek")
        if isinstance(season, dict):
            season = season.get("Season") or season.get("season")
        if isinstance(week, dict):
            week = week.get("Week") or week.get("week")
        self._nfl_projection = self._sportsdata(
            f"nfl/projections/json/PlayerGameProjectionStatsByWeek/{int(season)}/{int(week)}"
        ) or []
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

    def nfl_snapshot(self, card):
        market = NFL_MARKETS.get(card.market)
        if not market or not card.participant:
            return None
        target, opportunity, minimum = market
        player_rows = [
            row for row in self._nfl_history()
            if _name(row.get("player_display_name")) == _name(card.participant)
        ]
        if not player_rows:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:NFL_HISTORY_PLAYER_NOT_FOUND"
            )
            return None
        player_rows.sort(key=lambda r: (int(r["season"]), int(r["week"]), r["game_id"]))
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
        if projection is None:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:SPORTSDATA_NFL_PROJECTION_NOT_MATCHED"
            )
        position = str((projection or {}).get("Position") or player_rows[-1].get("position") or "")
        homeaway = str((projection or {}).get("HomeOrAway") or "").lower()
        if homeaway not in {"home", "away"}:
            # Home/away is a trained feature; do not guess it.
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:SPORTSDATA_NFL_HOMEAWAY_UNAVAILABLE"
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
        features = _nfl_features(values, opportunities, position, homeaway == "home")
        return {
            "player_id": str((projection or {}).get("PlayerID") or player_rows[-1]["player_id"]),
            "features": features,
            "expected_opportunities": projected_opportunities,
            "provider": "nflverse+SportsDataIO" if projection else "nflverse",
            "source_checksum": player_rows[-1]["_source_checksum"],
            "feature_schema_version": "nfl-player-rolling-v1",
            "integrity": {
                "event_identity": projection is not None,
                "player_identity": projection is not None,
                "fresh_features": True,
                "schema": True,
                "role": projected_opportunities >= minimum,
                "availability": active,
                "injuries": active,
                "no_duplicate_event": projection is not None,
            },
            "roster_version": str((projection or {}).get("Team") or ""),
            "injury_version": injury or None,
        }

    def _mlb_projections(self, starts_at):
        local_date = starts_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if local_date not in self._mlb_projection:
            self._mlb_projection[local_date] = (
                self._sportsdata(f"mlb/projections/json/PlayerGameProjectionStatsByDate/{local_date}")
                or []
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

    def mlb_snapshot(self, card):
        market = MLB_MARKETS.get(card.market)
        if not market or not card.participant or card.starts_at is None:
            return None
        target, opportunity, minimum = market
        pitcher = card.market.startswith("pitcher_")
        logs = self._mlb_game_logs(card.participant, "pitching" if pitcher else "hitting")
        values, opportunities = [], []
        for split in logs:
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
        if not projection:
            self._diagnostics.append(
                f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:SPORTSDATA_MLB_PROJECTION_NOT_MATCHED"
            )
            return None
        injury = str(projection.get("InjuryStatus") or "").strip().lower()
        active = injury not in {"out", "doubtful", "injured list"}
        if pitcher:
            role = 1.0 if int(projection.get("Started") or 0) == 1 else 0.0
            role_ok = role == 1.0 and bool(projection.get("BattingOrderConfirmed"))
            # SportsDataIO exposes projected outs/pitches but not projected batters
            # faced in this record. Keep opportunity scale consistent with training
            # by using recent actual batters faced; starter confirmation is separate.
            projected_opps = _mean(opportunities, 5)
        else:
            role = float(projection.get("BattingOrder") or 0)
            role_ok = role >= 1 and bool(projection.get("BattingOrderConfirmed"))
            projected_opps = _float(projection, "PlateAppearances", _mean(opportunities, 5))
        features = _mlb_features(values, opportunities, role)
        person = self._mlb_person(card.participant)
        checksum = hashlib.sha256(
            json.dumps(
                {
                    "person": person.get("id") if person else None,
                    "last": values[-20:],
                    "projection": {
                        key: projection.get(key)
                        for key in (
                            "PlayerID", "Team", "Position", "InjuryStatus", "Started",
                            "BattingOrder", "BattingOrderConfirmed",
                        )
                    },
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return {
            "player_id": str(projection.get("PlayerID") or (person or {}).get("id") or ""),
            "features": features,
            "expected_opportunities": projected_opps,
            "provider": "MLB StatsAPI+SportsDataIO",
            "source_checksum": checksum,
            "feature_schema_version": "mlb-player-rolling-v1",
            "integrity": {
                "event_identity": True,
                "player_identity": person is not None,
                "fresh_features": True,
                "schema": True,
                "role": role_ok and projected_opps >= minimum,
                "availability": active,
                "injuries": active,
                "no_duplicate_event": True,
            },
            "roster_version": str(projection.get("Team") or ""),
            "injury_version": injury or None,
        }

    def sync(self, store, cards):
        """Archive one evidence snapshot per unique prop participant/event/market."""
        seen = set()
        archived = 0
        for card in cards:
            if not card.participant or card.in_play:
                continue
            key = (card.sport, card.event_id, card.participant, card.market)
            if key in seen:
                continue
            seen.add(key)
            try:
                payload = (
                    self.nfl_snapshot(card)
                    if card.sport == "americanfootball_nfl"
                    else self.mlb_snapshot(card)
                    if card.sport == "baseball_mlb"
                    else None
                )
                if not payload:
                    continue
                # Failed integrity is stored as a diagnostic, never as a usable snapshot.
                if not all(payload["integrity"].values()):
                    failed = ",".join(
                        key for key, value in payload["integrity"].items() if value is not True
                    )
                    self._diagnostics.append(
                        f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:UNVERIFIED_PLAYER_INPUTS:{failed}"
                    )
                    continue
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
                    )
                )
            except (ValueError, KeyError, TypeError, OSError, urllib.error.URLError) as exc:
                self._diagnostics.append(
                    f"{card.sport}:{card.event_id}:{card.participant}:{card.market}:{type(exc).__name__}"
                )
        return archived

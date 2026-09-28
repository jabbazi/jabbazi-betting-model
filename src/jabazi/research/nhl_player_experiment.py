"""Causal NHL player-prop dataset construction from official completed-game records.

The builder consumes separately captured NHL schedule and Stats REST records. It creates
one pregame feature row per player/game using only results whose conservative
available_at timestamp precedes the prediction timestamp. No sportsbook line,
injury status, lineup status, or starting-goalie designation is invented.

This module builds research data only. Market-relative validation is a separate
prospective process.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import hashlib
import json
import math

from jabazi.models.team_elo import timestamp
from jabazi.providers.nhl import NAMES, canonical
from jabazi.providers.nhl_player_features import rolling_features

SPORT = "icehockey_nhl"
INITIAL_MARKETS = frozenset({
    "player_points",
    "player_assists",
    "player_shots_on_goal",
    "player_goals",
    "player_total_saves",
})
TARGETS = {
    "player_points": ("skater", "points", "timeOnIcePerGame", 8.0),
    "player_assists": ("skater", "assists", "timeOnIcePerGame", 8.0),
    "player_shots_on_goal": ("skater", "shots", "timeOnIcePerGame", 8.0),
    "player_goals": ("skater", "goals", "timeOnIcePerGame", 8.0),
    "player_total_saves": ("goalie", "saves", "shotsAgainst", 15.0),
}
TEAM_BY_ABBREV = {abbrev: canonical(name) for abbrev, name in NAMES.items()}


def _float(row, key):
    value = row.get(key)
    if value in (None, "", "NA"):
        raise ValueError(f"Missing NHL historical field {key}")
    if isinstance(value, str) and ":" in value:
        minutes, seconds = value.split(":", 1)
        value = float(minutes) + float(seconds) / 60.0
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite NHL historical field {key}")
    return value


def _player_id(row):
    value = row.get("playerId")
    if isinstance(value, bool):
        raise ValueError("Invalid NHL player id")
    value = int(value)
    if value <= 0:
        raise ValueError("Invalid NHL player id")
    return str(value)


def _game_id(row):
    value = row.get("gameId")
    if isinstance(value, bool):
        raise ValueError("Invalid NHL game id")
    value = int(value)
    if value <= 0:
        raise ValueError("Invalid NHL game id")
    return str(value)


def _team(row):
    raw = str(row.get("teamAbbrevs") or row.get("teamAbbrev") or "").strip()
    pieces = [piece.strip().upper() for piece in raw.replace(",", " ").split() if piece.strip()]
    if len(pieces) != 1 or pieces[0] not in TEAM_BY_ABBREV:
        raise ValueError("NHL historical player team identity is ambiguous")
    return pieces[0]


def _name(row, kind):
    value = row.get("goalieFullName" if kind == "goalie" else "skaterFullName")
    if not value:
        value = row.get("playerName")
    if not value:
        raise ValueError("NHL historical player name missing")
    return str(value)


def _position(row, kind):
    if kind == "goalie":
        return "G"
    value = str(row.get("positionCode") or "").upper()
    if value not in {"C", "L", "R", "LW", "RW", "D", "F"}:
        raise ValueError("NHL historical skater position missing")
    return value


def _mean(values, n):
    values = list(values)[-n:]
    return sum(values) / len(values) if values else 0.0


def schedule_index(games):
    index = {}
    for game in games:
        if not game.get("completed"):
            continue
        gid = str(game.get("game_id") or "")
        if not gid or gid in index:
            raise ValueError("Duplicate or missing NHL schedule game identity")
        start = timestamp(game["starts_at"])
        available = timestamp(game["available_at"])
        if available <= start:
            raise ValueError("Invalid NHL result availability")
        index[gid] = {
            "starts_at": start,
            "available_at": available,
            "home_team": canonical(game["home_team"]),
            "away_team": canonical(game["away_team"]),
        }
    return index


def _normalize_stats(rows, games, market):
    kind, target, opportunity, minimum = TARGETS[market]
    result = []
    seen = set()
    for raw in rows:
        pid, gid = _player_id(raw), _game_id(raw)
        key = (pid, gid)
        if key in seen:
            raise ValueError("Duplicate NHL player-game stat row")
        seen.add(key)
        game = games.get(gid)
        if not game:
            continue
        abbrev = _team(raw)
        team = TEAM_BY_ABBREV[abbrev]
        if team not in {game["home_team"], game["away_team"]}:
            raise ValueError("NHL player stat team does not match schedule event")
        value, opp = _float(raw, target), _float(raw, opportunity)
        if value < 0 or int(value) != value or opp < 0:
            raise ValueError("NHL player target/opportunity is invalid")
        result.append({
            "player_id": pid,
            "player_name": _name(raw, kind),
            "position": _position(raw, kind),
            "game_id": gid,
            "starts_at": game["starts_at"],
            "result_available_at": game["available_at"],
            "team": team,
            "is_home": team == game["home_team"],
            "observed_value": int(value),
            "opportunity": opp,
            "minimum": minimum,
        })
    return sorted(result, key=lambda r: (r["starts_at"], r["game_id"], r["player_id"]))


def build_dataset(
    *,
    games,
    skater_rows,
    goalie_rows,
    market,
    source_checksum,
    research_rights_reference,
    prediction_lead_hours=6,
):
    """Build one causally lagged player-prop dataset.

    prediction_lead_hours is predeclared and must be positive. Historical
    sportsbook prices are intentionally absent unless captured separately.
    """
    if market not in INITIAL_MARKETS:
        raise ValueError("NHL market not enabled for the initial player experiment")
    if (
        not source_checksum
        or not research_rights_reference
        or not isinstance(prediction_lead_hours, int)
        or not 1 <= prediction_lead_hours <= 24
    ):
        raise ValueError("NHL dataset provenance and prediction timing are required")

    games_by_id = schedule_index(games)
    kind = TARGETS[market][0]
    stats = _normalize_stats(
        goalie_rows if kind == "goalie" else skater_rows,
        games_by_id,
        market,
    )
    prior = defaultdict(list)
    output = []
    for current in stats:
        prediction_at = current["starts_at"] - timedelta(hours=prediction_lead_hours)
        history = [
            row for row in prior[current["player_id"]]
            if row["result_available_at"] < prediction_at
        ]
        values = [row["observed_value"] for row in history]
        opportunities = [row["opportunity"] for row in history]
        if len(values) >= 5 and _mean(opportunities, 5) >= current["minimum"]:
            features = rolling_features(
                values[-40:],
                opportunities[-40:],
                is_home=current["is_home"],
                position=current["position"],
            )
            latest_available = max(row["result_available_at"] for row in history)
            output.append({
                "event_id": current["game_id"],
                "player_id": current["player_id"],
                "participant": current["player_name"],
                "prediction_at": prediction_at.isoformat(),
                "features_available_at": latest_available.isoformat(),
                "starts_at": current["starts_at"].isoformat(),
                "result_available_at": current["result_available_at"].isoformat(),
                "result_status": "final",
                "observed_value": current["observed_value"],
                "expected_opportunities": _mean(opportunities, 5),
                "features": features,
                "market_line": None,
                "market_side": None,
                "market_no_vig_probability": None,
                "closing_no_vig_probability": None,
                "integrity": {
                    "event_identity": True,
                    "player_identity": True,
                    "historical_result_lagged": True,
                    "same_day_availability_verified": False,
                    "injury_status_verified": False,
                    "goalie_starter_verified": False if kind == "goalie" else None,
                },
            })
        prior[current["player_id"]].append(current)

    schema = sorted(output[0]["features"]) if output else []
    canonical = json.dumps(
        {
            "market": market,
            "source_checksum": source_checksum,
            "prediction_lead_hours": prediction_lead_hours,
            "rows": [
                [
                    row["event_id"],
                    row["player_id"],
                    row["prediction_at"],
                    row["observed_value"],
                    row["features"],
                ]
                for row in output
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    dataset_checksum = hashlib.sha256(canonical.encode()).hexdigest()
    return {
        "manifest": {
            "sport": SPORT,
            "market": market,
            "data_mode": "real",
            "provider": "NHL official schedule + Stats REST",
            "source_checksum": source_checksum,
            "dataset_checksum": dataset_checksum,
            "research_rights_reference": research_rights_reference,
            "feature_schema_version": "nhl-player-rolling-v1",
            "prediction_lead_hours": prediction_lead_hours,
            "market_prices_included": False,
            "limitations": [
                "No historical NHL player-prop price archive is included.",
                "Same-day injuries and scratches are not reconstructed.",
                "Historical starting-goalie confirmation is not reconstructed.",
                "Result availability uses a conservative schedule-based 48-hour lag.",
            ],
            "feature_names": schema,
        },
        "rows": output,
    }

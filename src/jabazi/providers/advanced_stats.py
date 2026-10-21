"""Pure import adapters for independently archived source payloads.

No network calls, API spend, inferred timestamps, or claims of live coverage.
Caller must supply captured evidence and certify a complete final game export.
"""

import math
import re
from collections import Counter


def _numeric(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a statistic")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError("Missing or malformed source statistic") from None
    if not math.isfinite(result):
        raise ValueError("Nonfinite source statistic")
    return result


def _count(value):
    result = _numeric(value)
    if result < 0 or int(result) != result:
        raise ValueError("Nonnegative integer count required")
    return int(result)


def innings_to_outs(value):
    """Baseball 5.2 means 17 outs, never 5.2 decimal innings."""
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.[012])?", value):
        raise ValueError("Use baseball innings notation as a string, e.g. 5.2")
    whole, _, remainder = value.partition(".")
    return 3 * int(whole) + int(remainder or "0")


def mlb_pitcher_snapshot(pitching, *, pitcher_id, started, evidence):
    """Normalize MLB-style box-score counters; this does not identify next starter.

    `started` describes the completed historical appearance only. A separate
    pregame announcement is required to join this pitcher to a future game.
    """
    if type(started) is not bool:
        raise ValueError("Explicit historical starter status required")
    values = {
        target: _count(pitching[source])
        for target, source in (
            ("batters_faced", "battersFaced"),
            ("strikeouts", "strikeOuts"),
            ("walks", "baseOnBalls"),
            ("earned_runs", "earnedRuns"),
            ("pitches", "numberOfPitches"),
        )
    }
    values.update(outs=innings_to_outs(pitching["inningsPitched"]), started=int(started))
    return {
        **evidence,
        "entity_id": pitcher_id,
        "kind": "mlb_pitcher",
        "status": "final",
        "values": values,
    }


def nfl_team_snapshots(plays, *, home_id, away_id, complete_final_game, evidence):
    """Aggregate one complete nflverse-style game (pass/run, no spikes/kneels).

    Include sacks when play_type=pass. Exclude penalties/no_play/special teams.
    Success is EPA > 0. EPA allowed stays in the offense's sign convention.
    This is a fixed feature definition, not an assertion of predictive value.
    """
    if complete_final_game is not True or not home_id or not away_id or home_id == away_id:
        raise ValueError("Complete final game and distinct canonical team IDs required")
    totals = {team: Counter() for team in (home_id, away_id)}
    seen = set()
    for play in plays:
        if play["game_id"] != evidence["event_id"]:
            raise ValueError("Mixed game export")
        pid = _numeric(play["play_id"])
        if pid <= 0 or int(pid) != pid or pid in seen:
            raise ValueError("Missing, duplicate, or malformed play ID")
        seen.add(pid)
        if play["play_type"] not in {"pass", "run"}:
            continue
        kneel, spike = (_count(play[k]) for k in ("qb_kneel", "qb_spike"))
        if kneel not in (0, 1) or spike not in (0, 1):
            raise ValueError("Malformed kneel/spike indicator")
        if kneel or spike:
            continue
        offense, defense = play["posteam"], play["defteam"]
        if set((offense, defense)) != set(totals):
            raise ValueError("Play team identity does not match game")
        epa = _numeric(play["epa"])
        totals[offense]["offense_plays"] += 1
        totals[offense]["offense_epa"] += epa
        totals[offense]["offense_successes"] += int(epa > 0)
        totals[defense]["defense_plays"] += 1
        totals[defense]["defense_epa_allowed"] += epa
        totals[defense]["defense_successes_allowed"] += int(epa > 0)
    fields = (
        "offense_plays",
        "offense_epa",
        "offense_successes",
        "defense_plays",
        "defense_epa_allowed",
        "defense_successes_allowed",
    )
    if any(t["offense_plays"] == 0 or t["defense_plays"] == 0 for t in totals.values()):
        raise ValueError("Empty or one-sided play-by-play coverage")
    return [
        {
            **evidence,
            "snapshot_id": evidence["snapshot_id"] + ":" + team,
            "entity_id": team,
            "kind": "nfl_team",
            "status": "final",
            "values": {field: t[field] for field in fields},
        }
        for team, t in totals.items()
    ]

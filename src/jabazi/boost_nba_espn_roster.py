"""Bounded public NBA roster adapter for GOAT identity candidate research.

Uses existing ESPN team/roster collection routines. A current ESPN roster
record and a BALLDONTLIE player record agreeing on name/team/jersey is
a review candidate, NOT an independently verified ID crosswalk.
"""
from __future__ import annotations

from datetime import UTC, datetime

from jabazi.providers.nba_player_features import (
    ESPN, NBAPlayerFeatureCollector, _json,
)


def fetch_nba_espn_roster(team_abbreviations, *, now=None):
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("Aware observation time required")
    if not isinstance(team_abbreviations, (set, frozenset, tuple, list)):
        raise ValueError("Explicit team abbreviations required")
    requested = set(team_abbreviations)
    if (not 1 <= len(requested) <= 4
            or any(not isinstance(t, str) or not t.isalpha()
                   or not 2 <= len(t) <= 4 for t in requested)):
        raise ValueError("Require 1-4 valid team abbreviations")
    requested = {x.upper() for x in requested}
    collector = NBAPlayerFeatureCollector(now=now)
    index = collector._team_index()
    selected = {}
    for _, info in index.items():
        abbreviation = str(info.get("abbr") or "").upper()
        if abbreviation in requested:
            if abbreviation in selected:
                raise ValueError("Ambiguous ESPN team abbreviation")
            selected[abbreviation] = info
    if set(selected) != requested:
        raise ValueError("Missing ESPN team identity")
    rows = []
    for abbr in sorted(requested):
        info = selected[abbr]
        payload, checksum = _json(f"{ESPN}/teams/{info['id']}/roster")
        groups = payload.get("athletes") if isinstance(payload, dict) else None
        if not isinstance(groups, list):
            raise ValueError("ESPN roster schema unavailable")
        seen = set()
        for group in groups:
            if not isinstance(group, dict):
                continue
            athletes = group.get("items")
            if not isinstance(athletes, list):
                athletes = [group] if group.get("id") else []
            for athlete in athletes:
                if not isinstance(athlete, dict):
                    continue
                player_id = str(athlete.get("id") or "").strip()
                name = athlete.get("displayName") or athlete.get("fullName")
                if not player_id or player_id in seen:
                    continue
                seen.add(player_id)
                rows.append({
                    "source_namespace": "ESPN",
                    "source_player_id": player_id,
                    "full_name": name,
                    "team_abbreviation": abbr,
                    "jersey_number": athlete.get("jersey"),
                    "position_abbreviation": (
                        (athlete.get("position") or {}).get("abbreviation")
                        if isinstance(athlete.get("position"), dict) else None
                    ),
                    "source_observed_at": datetime.now(UTC).isoformat(),
                    "source_response_sha256": checksum,
                })
    if not rows:
        raise ValueError("No usable ESPN roster records")
    return rows

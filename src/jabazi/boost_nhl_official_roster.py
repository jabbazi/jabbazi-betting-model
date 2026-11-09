"""NHL official current-roster evidence for private, unapproved identity candidates.

Only independent official roster records; no model or wagering approval.
"""
from __future__ import annotations
from datetime import UTC, datetime
from jabazi.providers.nhl_player_features import WEB_BASE, _fetch_json


def fetch_nhl_official_roster(team_abbreviations, *, now=None):
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("Timezone-aware roster observation required")
    if not isinstance(team_abbreviations, (list, tuple, set, frozenset)):
        raise ValueError("Explicit NHL teams required")
    teams = set(team_abbreviations)
    if (not 1 <= len(teams) <= 4
            or any(not isinstance(t, str) or not t.isalpha() or
                   not 2 <= len(t) <= 4 for t in teams)):
        raise ValueError("Require 1-4 NHL team abbreviations")
    rows = []
    for team in sorted(t.upper() for t in teams):
        payload, checksum = _fetch_json(f"{WEB_BASE}/roster/{team}/current")
        if not isinstance(payload, dict):
            raise ValueError("Invalid NHL roster schema")
        for group in ("forwards", "defensemen", "goalies"):
            players = payload.get(group)
            if not isinstance(players, list):
                raise ValueError("Incomplete NHL roster schema")
            for player in players:
                if not isinstance(player, dict):
                    raise ValueError("Invalid NHL roster player")
                name = player.get("firstName")
                surname = player.get("lastName")
                first = name.get("default") if isinstance(name, dict) else None
                last = surname.get("default") if isinstance(surname, dict) else None
                ident = player.get("id")
                position = player.get("positionCode")
                if not (type(ident) is int and ident > 0 and first and last
                        and isinstance(position, str) and position):
                    continue
                rows.append({
                    "source_namespace": "NHL",
                    "source_player_id": str(ident),
                    "full_name": str(first) + " " + str(last),
                    "team_abbreviation": team,
                    "position_abbreviation": position,
                    "source_observed_at": now.astimezone(UTC).isoformat(),
                    "source_response_sha256": checksum,
                })
    if not rows:
        raise ValueError("No NHL official roster evidence")
    return rows

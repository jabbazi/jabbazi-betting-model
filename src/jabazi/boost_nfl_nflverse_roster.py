"""Bounded nflverse season roster adapter for GOAT NFL identity candidates.

Downloads the documented nflverse roster_<season>.csv release. Roster rows
contain GSIS IDs, names, teams, positions and jerseys. This is independent
source evidence for *candidate review*, not proof of BALLDONTLIE identity.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime

from jabazi.providers.player_features_live import _fetch_bytes

URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
       "rosters/roster_{season}.csv")
REQUIRED = frozenset({"season", "team", "position", "jersey_number",
                      "full_name", "gsis_id"})


def fetch_nfl_nflverse_roster(team_abbreviations, *, now=None):
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("Aware observation time required")
    if not isinstance(team_abbreviations, (set, frozenset, list, tuple)):
        raise ValueError("Explicit team abbreviations required")
    requested = set(team_abbreviations)
    if (not 1 <= len(requested) <= 4
            or any(not isinstance(x, str) or not x.isalpha()
                   or not 2 <= len(x) <= 4 for x in requested)):
        raise ValueError("Require 1-4 valid team abbreviations")
    requested = {x.upper() for x in requested}
    season = now.year if now.month >= 7 else now.year - 1
    raw = _fetch_bytes(URL.format(season=season), max_bytes=16_000_000)
    checksum = hashlib.sha256(raw).hexdigest()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
        raise ValueError("nflverse roster schema mismatch")
    rows = []
    for index, record in enumerate(reader):
        if index >= 10000:
            raise ValueError("Unexpectedly large nflverse roster")
        if str(record.get("season") or "") != str(season):
            continue
        team = str(record.get("team") or "").upper()
        if team not in requested:
            continue
        ident = str(record.get("gsis_id") or "").strip()
        if not ident:
            continue
        rows.append({
            "source_namespace": "NFLVERSE",
            "source_player_id": ident,
            "full_name": record.get("full_name"),
            "team_abbreviation": team,
            "jersey_number": record.get("jersey_number"),
            "position_abbreviation": record.get("position"),
            "source_observed_at": datetime.now(UTC).isoformat(),
            "source_response_sha256": checksum,
        })
    if not rows:
        raise ValueError("No matching nflverse roster records")
    return rows

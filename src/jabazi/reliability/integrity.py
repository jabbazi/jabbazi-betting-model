"""Deterministic identity contracts. Missing critical metadata is not confirmation."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True)
class Identity:
    event_id: str
    home_team: str
    away_team: str
    starts_at: datetime
    season: int | None = None
    week: int | None = None


def compare_identity(observed, expected):
    failures = []
    for name in ("event_id", "home_team", "away_team", "season", "week"):
        a, b = getattr(observed, name), getattr(expected, name)
        if a is None or b is None:
            failures.append("UNVERIFIED_" + name.upper())
        elif a != b:
            failures.append(name.upper() + "_MISMATCH")
    if observed.starts_at.tzinfo is None or expected.starts_at.tzinfo is None:
        failures.append("UNZONED_START")
    elif abs((observed.starts_at - expected.starts_at).total_seconds()) > 60:
        failures.append("START_TIME_MISMATCH")
    if observed.home_team == observed.away_team:
        failures.append("DUPLICATE_TEAM")
    return failures


def duplicate_event_ids(quotes):
    by_id = {}
    by_game = {}
    bad = set()
    for q in quotes:
        identity = (q.sport, q.event_name, q.commence_time)
        by_id.setdefault(q.event_id, set()).add(identity)
        by_game.setdefault(identity, set()).add(q.event_id)
    for event, identities in by_id.items():
        if len(identities) > 1:
            bad.add(event)
    for ids in by_game.values():
        if len(ids) > 1:
            bad.update(ids)
    return bad


def feature_contract(
    values, means, scales, *, maximum_z=6, missing_fraction=0, maximum_missing=0.05
):
    if len(values) != len(means) or len(values) != len(scales):
        return ["FEATURE_SCHEMA_MISMATCH"]
    if not 0 <= missing_fraction <= maximum_missing:
        return ["EXCESSIVE_MISSING_FEATURES"]
    failures = []
    for i, (v, m, s) in enumerate(zip(values, means, scales)):
        if v is None or not all(isfinite(x) for x in (v, m, s)) or s <= 0:
            failures.append(f"INVALID_FEATURE_{i}")
        elif abs((v - m) / s) > maximum_z:
            failures.append(f"FEATURE_DRIFT_{i}")
    return failures

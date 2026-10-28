"""Fail-closed research-only reconciliation of LAB signals and Sports API props.

A successful identity join does not produce a calibrated hit probability or an
executable SGP ticket. Only identical provider game/player IDs, stat labels and
numeric lines are eligible; ambiguous duplicates are rejected.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation


def _id(value):
    return type(value) is int and value > 0


def _line(value):
    if isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None
    return n.normalize() if n.is_finite() and n >= 0 else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(UTC) if t.tzinfo is not None and t.utcoffset() is not None else None


def reconcile_paid_player_research(sport, lab_rows, sportsbook_rows, *, observed_at,
                                   max_age=timedelta(minutes=15)):
    """Return aggregate reconciliation only; never a probability or licensed row.

    LAB and Sports API identifiers must share the exact provider namespace.
    This function cannot establish that namespace from its inputs; operators
    must verify source provenance separately before treating any join as valid.
    """
    if sport not in ("NBA", "NFL"):
        raise ValueError("LAB player-prop reconciliation supports NBA/NFL only")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Aware observation time required")
    if max_age <= timedelta(0):
        raise ValueError("Positive freshness window required")
    now = observed_at.astimezone(UTC)
    reasons = Counter()
    lab = defaultdict(list)
    for row in lab_rows:
        if not isinstance(row, dict) or row.get("sport") != sport:
            reasons["lab_wrong_sport_or_schema"] += 1
            continue
        game, player = row.get("game_id"), row.get("player_id")
        market = row.get("market")
        line = _line(row.get("market_line"))
        if (not _id(game) or not _id(player) or not isinstance(market, str)
                or not market.strip() or line is None):
            reasons["lab_missing_exact_identity_or_line"] += 1
            continue
        stamp = _timestamp(row.get("created_at"))
        if stamp is None or not timedelta(0) <= now - stamp <= max_age:
            reasons["lab_stale_or_missing_timestamp"] += 1
            continue
        if row.get("hit_probability_verified") is True or row.get("model_hit_probability") is not None:
            reasons["lab_unverified_probability_claim"] += 1
            continue
        key = (game, player, market.strip().lower(), line)
        lab[key].append(row)
    # Multiple saved predictions for the same exact identity are ambiguous.
    ambiguous = {key for key, rows in lab.items() if len(rows) != 1}
    reasons["lab_ambiguous_exact_identity"] += len(ambiguous)
    offers = defaultdict(list)
    for wrapper in sportsbook_rows:
        if not isinstance(wrapper, dict) or wrapper.get("sport") not in (sport, {"NBA":"basketball_nba","NFL":"americanfootball_nfl"}[sport]):
            reasons["odds_wrong_sport_or_schema"] += 1
            continue
        raw = wrapper.get("raw")
        if not isinstance(raw, dict):
            reasons["odds_invalid_schema"] += 1
            continue
        game, player = raw.get("game_id"), raw.get("player_id")
        market = raw.get("prop_type")
        line = _line(raw.get("line_value"))
        if (not _id(game) or not _id(player) or not isinstance(market, str)
                or not market.strip() or line is None):
            reasons["odds_missing_exact_identity_or_line"] += 1
            continue
        stamp = _timestamp(raw.get("updated_at"))
        if stamp is None or not timedelta(0) <= now - stamp <= max_age:
            reasons["odds_stale_or_missing_timestamp"] += 1
            continue
        key = (game, player, market.strip().lower(), line)
        offers[key].append(raw)
    matched = 0
    for key in lab:
        if key in ambiguous:
            continue
        if key in offers:
            matched += 1
        else:
            reasons["lab_without_matching_exact_offer"] += 1
    return {
        "sport": sport, "observed_at": now.isoformat(),
        "lab_rows_received": len(lab_rows),
        "sportsbook_rows_received": len(sportsbook_rows),
        "unique_exact_identity_joins": matched,
        "rejections": dict(sorted(reasons.items())),
        "identity_namespace_independently_verified": False,
        "calibrated_exact_line_hit_probabilities_verified": False,
        "joint_probability_validated": False,
        "betting_enabled": False,
        "approval": "RESEARCH_ONLY",
    }

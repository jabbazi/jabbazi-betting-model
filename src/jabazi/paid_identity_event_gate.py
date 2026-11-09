"""Strict pregame event membership gate for PRIVATE identity-review candidates.

Checks provider game ID, kickoff and teams against a roster candidate. This is
structural input evidence only: never an identity attestation or wager approval.
"""
from __future__ import annotations
from datetime import UTC, datetime
from collections import Counter

START_FIELDS = {"NBA": "datetime", "NFL": "date", "NHL": "start_time_utc"}
SOURCE_NAMESPACES = {"NBA": "ESPN", "NFL": "NFLVERSE", "NHL": "NHL"}


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.utcoffset() is not None else None
    except ValueError:
        return None


def _team(row):
    if not isinstance(row, dict):
        return None
    value = row.get("tricode") or row.get("abbreviation")
    return value.upper() if isinstance(value, str) and 2 <= len(value) <= 4 and value.isalpha() else None


def audit_candidate_game_context(sport, game, candidate_rows, *, observed_at):
    """Return deidentified counts and per-candidate accept flags for private use.

    A true game-match is NOT an independently reviewed player identity. The
    caller cannot use this function to set provider_identity_verified.
    """
    if sport not in START_FIELDS:
        raise ValueError("Unsupported sport")
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        raise ValueError("Timezone-aware observation required")
    if not isinstance(candidate_rows, list) or len(candidate_rows) > 1000:
        raise ValueError("Bounded candidate list required")
    now = observed_at.astimezone(UTC)
    issues = Counter()
    accepted = []
    if not isinstance(game, dict) or type(game.get("id")) is not int or game["id"] <= 0:
        issues["INVALID_GAME_ID"] += len(candidate_rows) or 1
        return _report(sport, accepted, issues)
    starts = _stamp(game.get(START_FIELDS[sport]))
    away = _team(game.get("visitor_team") or game.get("away_team"))
    home = _team(game.get("home_team"))
    if (starts is None or starts <= now or
            game.get("status_state") != "scheduled" or
            not away or not home or away == home):
        issues["GAME_STATUS_KICKOFF_OR_TEAMS_UNVERIFIED"] += len(candidate_rows) or 1
        return _report(sport, accepted, issues)
    for candidate in candidate_rows:
        if not isinstance(candidate, dict):
            issues["INVALID_CANDIDATE"] += 1
            continue
        evidence = candidate.get("review_evidence_private")
        if (candidate.get("sport") != sport or
                candidate.get("source_namespace") != SOURCE_NAMESPACES[sport] or
                candidate.get("review_state") != "CANDIDATE_REQUIRES_INDEPENDENT_VERIFICATION" or
                candidate.get("independent_source_reviewed") is not False or
                candidate.get("provider_identity_verified") is not False or
                not isinstance(evidence, dict)):
            issues["CANDIDATE_PROVENANCE_INVALID"] += 1
            continue
        if _stamp(evidence.get("event_starts_at")) != starts:
            issues["EVENT_KICKOFF_MISMATCH"] += 1
            continue
        team = candidate.get("team_abbreviation")
        if team not in (away, home) or evidence.get("team_abbreviation") != team:
            issues["PLAYER_TEAM_NOT_IN_GAME"] += 1
            continue
        accepted.append(candidate)
    return _report(sport, accepted, issues)


def _report(sport, accepted, issues):
    return {
        "sport": sport,
        "private_event_membership_candidates": accepted,
        "redacted_summary": {
            "sport": sport, "structurally_game_eligible_candidate_count": len(accepted),
            "rejections": dict(sorted(issues.items())),
            "identities_independently_verified": 0,
            "features_verified": False,
            "model_probabilities_verified": False,
            "betting_enabled": False,
            "status": "CANDIDATES_ONLY",
        },
    }

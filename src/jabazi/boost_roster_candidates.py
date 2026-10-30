"""Private, deterministic GOAT-to-ESPN/nflverse roster candidate matching.

This is a *candidate generator*, not an authenticated player-ID crosswalk.
It uses exact normalized name + team + jersey, and NFL position when present.
Names/jerseys can change or collide. No candidate may automatically acquire
provider_identity_verified or independent_source_reviewed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
import unicodedata

SOURCE_NAMESPACE = {"NBA": "ESPN", "NFL": "NFLVERSE"}


def _name(value):
    if not isinstance(value, str):
        return None
    ascii_name = "".join(
        ch for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    ).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "", ascii_name)
    return normalized or None


def _jersey(value):
    if isinstance(value, bool):
        return None
    text = str(value).strip() if value is not None else ""
    if not re.fullmatch(r"[0-9]{1,3}", text):
        return None
    return str(int(text))


def _team(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2,4}", value.strip()):
        return None
    return value.strip().upper()


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.utcoffset() is not None else None


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode()).hexdigest()


def match_roster_candidates(sport, bdl_players, source_roster, *,
                            observed_at, event_starts_at):
    """Return private candidates and de-identified diagnostics.

    The caller must keep candidates in a private environment and independently
    compare original provider records before attesting a crosswalk.
    """
    if sport not in SOURCE_NAMESPACE:
        raise ValueError("NBA or NFL required")
    if (not isinstance(observed_at, datetime)
            or observed_at.utcoffset() is None):
        raise ValueError("Timezone-aware observation required")
    start = _stamp(event_starts_at)
    now = observed_at.astimezone(UTC)
    if start is None or now >= start:
        raise ValueError("Upcoming verified kickoff required")
    if (not isinstance(bdl_players, list) or not isinstance(source_roster, list)
            or len(bdl_players) > 1000 or len(source_roster) > 1000):
        raise ValueError("Bounded roster lists required")
    reasons = Counter()
    bdl_index, source_index = defaultdict(list), defaultdict(list)
    seen_bdl, seen_source = set(), set()
    for row in bdl_players:
        if not isinstance(row, dict):
            reasons["bdl_invalid_schema"] += 1
            continue
        ident = row.get("id")
        team = row.get("team")
        key = (
            _name(str(row.get("first_name") or "") + " " + str(row.get("last_name") or "")),
            _team(team.get("abbreviation")) if isinstance(team, dict) else None,
            _jersey(row.get("jersey_number")),
        )
        if type(ident) is not int or ident <= 0 or any(x is None for x in key):
            reasons["bdl_missing_identity_factors"] += 1
            continue
        if ident in seen_bdl:
            reasons["bdl_duplicate_player_id"] += 1
            # Keep duplicate ID in index to reject it, rather than selecting first.
        seen_bdl.add(ident)
        bdl_index[key].append(row)
    for row in source_roster:
        if not isinstance(row, dict):
            reasons["source_invalid_schema"] += 1
            continue
        ident = row.get("source_player_id")
        stamp = _stamp(row.get("source_observed_at"))
        key = (
            _name(row.get("full_name")),
            _team(row.get("team_abbreviation")),
            _jersey(row.get("jersey_number")),
        )
        if (row.get("source_namespace") != SOURCE_NAMESPACE[sport]
                or not isinstance(ident, str) or not ident.strip()
                or any(x is None for x in key)
                or stamp is None or not now - timedelta(hours=48) <= stamp <= now
                or stamp >= start):
            reasons["source_missing_or_stale_identity_factors"] += 1
            continue
        if ident in seen_source:
            reasons["source_duplicate_player_id"] += 1
        seen_source.add(ident)
        source_index[key].append(row)
    candidates = []
    for key, bdl_rows in bdl_index.items():
        source_rows = source_index.get(key, [])
        if not source_rows:
            reasons["no_exact_name_team_jersey_candidate"] += len(bdl_rows)
            continue
        if len(bdl_rows) != 1 or len(source_rows) != 1:
            reasons["ambiguous_identity_factors"] += len(bdl_rows)
            continue
        bdl, source = bdl_rows[0], source_rows[0]
        if sport == "NFL":
            bpos = str(bdl.get("position_abbreviation") or "").upper()
            spos = str(source.get("position_abbreviation") or "").upper()
            if not bpos or not spos or bpos != spos:
                reasons["nfl_position_conflict"] += 1
                continue
        candidates.append({
            "sport": sport,
            "bdl_player_id": bdl["id"],
            "source_namespace": SOURCE_NAMESPACE[sport],
            "source_player_id": source["source_player_id"],
            "team_abbreviation": key[1],
            "bdl_record_sha256": _digest(bdl),
            "source_record_sha256": _digest(source),
            "match_factors": ["exact_normalized_name", "team_abbreviation",
                              "jersey_number"] + (["position_abbreviation"] if sport == "NFL" else []),
            "review_state": "CANDIDATE_REQUIRES_INDEPENDENT_VERIFICATION",
            "provider_identity_verified": False,
            "independent_source_reviewed": False,
        })
    return {
        "sport": sport,
        "observed_at": now.isoformat(),
        "candidate_count": len(candidates),
        "rejections": dict(sorted(reasons.items())),
        "candidates_private": candidates,
        "independently_verified_crosswalks": 0,
        "model_probabilities_verified": False,
        "betting_enabled": False,
        "approval": "RESEARCH_ONLY",
    }


def redacted_candidate_summary(report):
    """Safe diagnostic for logs/chat; deliberately drops all player identifiers."""
    return {
        "sport": report["sport"],
        "observed_at": report["observed_at"],
        "candidate_count": report["candidate_count"],
        "rejections": report["rejections"],
        "independently_verified_crosswalks": 0,
        "model_probabilities_verified": False,
        "betting_enabled": False,
        "approval": "RESEARCH_ONLY",
    }

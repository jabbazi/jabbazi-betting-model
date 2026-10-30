"""Deterministic, fail-closed cross-provider player identity manifest audit.

Manifest is assembled from independently reviewed provider records in a private
runtime. This audit checks schema, temporal ordering, provenance fingerprints,
and ambiguous ID mappings. It cannot establish real-world identity by itself.
No fuzzy names, no probability estimation, no automatic approval.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from hashlib import sha256
import json
import re

SOURCE_NAMESPACE = {"NBA": "ESPN", "NFL": "NFLVERSE"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.utcoffset() is not None else None


def _id(value):
    return type(value) is int and value > 0


def crosswalk_digest(record):
    """Canonical SHA-256 fingerprint, excluding the declared digest itself."""
    payload = {k: v for k, v in record.items() if k != "record_sha256"}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode()).hexdigest()


def audit_identity_manifest(sport, records, *, observed_at):
    if sport not in SOURCE_NAMESPACE:
        raise ValueError("Only NBA and NFL are supported")
    if observed_at.utcoffset() is None:
        raise ValueError("Aware audit time required")
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("Bounded list required")
    now = observed_at.astimezone(UTC)
    reasons = Counter()
    accepted = defaultdict(list)
    for record in records:
        if not isinstance(record, dict) or record.get("sport") != sport:
            reasons["invalid_sport_or_schema"] += 1
            continue
        bdl_game, bdl_player = record.get("bdl_game_id"), record.get("bdl_player_id")
        source_id, source_ns = record.get("source_player_id"), record.get("source_namespace")
        kickoff = _time(record.get("event_starts_at"))
        reviewed = _time(record.get("reviewed_at"))
        source_hash = record.get("source_record_sha256")
        declared_hash = record.get("record_sha256")
        if (not _id(bdl_game) or not _id(bdl_player)
                or not isinstance(source_id, str) or not source_id.strip()
                or source_ns != SOURCE_NAMESPACE[sport]
                or not isinstance(record.get("team_id"), str)
                or not record["team_id"].strip()
                or kickoff is None or reviewed is None
                or not reviewed <= now < kickoff
                or not isinstance(source_hash, str) or not SHA256.fullmatch(source_hash)
                or not isinstance(declared_hash, str) or not SHA256.fullmatch(declared_hash)
                or record.get("independent_source_reviewed") is not True):
            reasons["missing_independent_identity_evidence"] += 1
            continue
        if crosswalk_digest(record) != declared_hash:
            reasons["crosswalk_fingerprint_mismatch"] += 1
            continue
        key = (bdl_game, bdl_player)
        accepted[key].append((source_ns, source_id.strip(), record["team_id"].strip()))
    # A player may appear in multiple games, but one BDL player cannot map
    # to two source identities, nor one source identity to two BDL players.
    bdl_to_source = defaultdict(set)
    source_to_bdl = defaultdict(set)
    for (_, bdl_player), rows in accepted.items():
        for source_ns, source_id, team_id in rows:
            bdl_to_source[bdl_player].add((source_ns, source_id))
            source_to_bdl[(source_ns, source_id)].add(bdl_player)
    verified = 0
    for (_, bdl_player), rows in accepted.items():
        if (len(rows) != 1
                or len(bdl_to_source[bdl_player]) != 1
                or len(source_to_bdl[(rows[0][0], rows[0][1])]) != 1):
            reasons["duplicate_or_conflicting_crosswalk"] += 1
        else:
            verified += 1
    return {
        "sport": sport,
        "records_received": len(records),
        "unique_structurally_valid_crosswalks": verified,
        "rejections": dict(sorted(reasons.items())),
        "independent_provider_truth_confirmed_by_runtime": False,
        "feature_snapshot_verified": False,
        "hit_probability_verified": False,
        "betting_enabled": False,
        "approval": "RESEARCH_ONLY",
    }

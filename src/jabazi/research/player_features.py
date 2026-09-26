"""Point-in-time player feature snapshot contract.

A scanner can only infer a player prop when a real pregame feature provider has
archived a fresh snapshot under this contract.  No synthetic defaults are allowed.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math

from jabazi.persistence.store import digest


REQUIRED_INTEGRITY = (
    "event_identity",
    "player_identity",
    "fresh_features",
    "schema",
    "role",
    "availability",
    "injuries",
    "no_duplicate_event",
)


def _timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone-aware player feature timestamp required")
    return dt.astimezone(UTC)


def _finite_features(features):
    if not isinstance(features, dict) or not features:
        raise ValueError("Named player feature vector required")
    clean = {}
    for name, value in features.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Invalid feature name")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Player features must be numeric")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Non-finite player feature")
        clean[name] = value
    return clean


def archive_player_feature_snapshot(
    store,
    *,
    sport,
    event_id,
    participant,
    market,
    player_id,
    starts_at,
    features_available_at,
    features,
    expected_opportunities,
    integrity,
    provider,
    source_checksum,
    feature_schema_version,
    roster_version=None,
    injury_version=None,
):
    """Archive immutable pregame features and return the snapshot id.

    This function does not fetch data.  The caller must provide real evidence from
    an authorized data source, including a checksum and timestamps.
    """
    if not all((sport, event_id, participant, market, player_id, provider, source_checksum, feature_schema_version)):
        raise ValueError("Player feature provenance and identity are required")
    start = _timestamp(starts_at)
    available = _timestamp(features_available_at)
    now = datetime.now(UTC)
    if available > now or available >= start:
        raise ValueError("Player features must exist before game start")
    vector = _finite_features(features)
    expected = float(expected_opportunities)
    if not math.isfinite(expected) or expected < 0:
        raise ValueError("Invalid expected opportunity estimate")
    if not isinstance(integrity, dict):
        raise ValueError("Integrity evidence must be a mapping")
    missing = [name for name in REQUIRED_INTEGRITY if integrity.get(name) is not True]
    if missing:
        raise ValueError("Unverified player feature integrity: " + ",".join(missing))

    canonical = {
        "sport": sport,
        "event_id": str(event_id),
        "participant": participant,
        "market": market,
        "player_id": str(player_id),
        "starts_at": start.isoformat(),
        "features_available_at": available.isoformat(),
        "feature_schema_version": feature_schema_version,
        "features": vector,
        "expected_opportunities": expected,
        "provider": provider,
        "source_checksum": source_checksum,
        "roster_version": roster_version,
        "injury_version": injury_version,
        "integrity": {name: True for name in REQUIRED_INTEGRITY},
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot_id = "playerfs-" + fingerprint[:20]
    payload = canonical | {
        "snapshot_id": snapshot_id,
        "archived_at": now.isoformat(),
    }
    entity = f"{sport}|{event_id}|{participant}|{market}"
    store.append(
        "player_feature_snapshot",
        entity,
        payload,
        digest(["player_feature_snapshot", snapshot_id]),
    )
    return snapshot_id

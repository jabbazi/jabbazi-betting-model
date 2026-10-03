"""Immutable granular research feature snapshots.

These records are intentionally separate from production player_feature_snapshot
artifacts. They can be used to train challengers, but cannot influence current cash
decisions until a new artifact explicitly declares the granular schema.
"""
from __future__ import annotations

from datetime import UTC, datetime
import math

from jabazi.persistence.store import digest


def archive_granular_snapshot(
    store, *, sport, event_id, participant, starts_at, available_at,
    features, provider, source_checksum, schema_version,
):
    if not all((sport,event_id,participant,provider,source_checksum,schema_version)):
        raise ValueError("Granular feature provenance required")
    start=datetime.fromisoformat(str(starts_at).replace("Z","+00:00"))
    available=datetime.fromisoformat(str(available_at).replace("Z","+00:00"))
    if start.tzinfo is None or available.tzinfo is None:
        raise ValueError("Granular timestamps must be aware")
    if available.astimezone(UTC)>=start.astimezone(UTC):
        raise ValueError("Granular features must be pregame")
    clean={}
    for name,value in features.items():
        if not isinstance(name,str) or not name:
            raise ValueError("Invalid granular feature name")
        if isinstance(value,bool) or not isinstance(value,(int,float)):
            raise ValueError("Granular features must be numeric")
        value=float(value)
        if not math.isfinite(value):
            raise ValueError("Non-finite granular feature")
        clean[name]=value
    if not clean:
        raise ValueError("Granular feature vector required")
    payload={
        "sport":sport,"event_id":str(event_id),"participant":participant,
        "starts_at":start.astimezone(UTC).isoformat(),
        "features_available_at":available.astimezone(UTC).isoformat(),
        "features":clean,"provider":provider,"source_checksum":source_checksum,
        "feature_schema_version":schema_version,
        "research_only":True,"cash_influence":False,
    }
    entity=f"{sport}|{event_id}|{participant}"
    return store.append(
        "granular_feature_snapshot",entity,payload,
        digest(["granular_feature_snapshot",entity,payload["features_available_at"],source_checksum]),
    )

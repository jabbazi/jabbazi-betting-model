"""Deidentified readiness report for the existing V7 paid player scanner.

No player IDs, quote data, secrets, provider calls, mutations or approvals.
Counts are league-wide evidence, NOT game/player/market acceptance.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlalchemy import text

SPORTS = {"NBA": "basketball_nba", "NFL": "americanfootball_nfl",
          "NHL": "icehockey_nhl"}


def summarize_readiness(models, manifest_counts, feature_counts, *, observed_at):
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        raise ValueError("Aware observation time required")
    sport_rows = {}
    for label, sport in SPORTS.items():
        model_rows = [
            model for (model_sport, _), model in models.items()
            if model_sport == sport
        ]
        count = int(manifest_counts.get(label, 0))
        recent = feature_counts.get(sport, {})
        fresh = int(recent.get("recent", 0))
        verified = int(recent.get("recent_verified", 0))
        if min(count, fresh, verified) < 0 or verified > fresh:
            raise ValueError("Inconsistent evidence counts")
        reasons = []
        if not model_rows:
            reasons.append("NO_LOADABLE_PLAYER_MODELS")
        if count == 0:
            reasons.append("NO_REGISTERED_REVIEWED_IDENTITY_MANIFEST")
        if fresh == 0:
            reasons.append("NO_RECENT_PLAYER_FEATURE_SNAPSHOTS")
        elif verified == 0:
            reasons.append("NO_RECENT_VERIFIED_PLAYER_FEATURE_SNAPSHOTS")
        if model_rows and any(
            model.stage != "PRODUCTION_APPROVED" for model in model_rows
        ):
            reasons.append("MODELS_NOT_FULLY_PRODUCTION_APPROVED")
        # Nonempty manifest and sport-wide features are prerequisites only.
        # No code in this audit certifies actual source IDs or game joins.
        if not reasons:
            reasons.append("SLATE_IDENTITY_AND_EXACT_LINE_INFERENCE_NOT_AUDITED")
        sport_rows[label] = {
            "loadable_player_models": len(model_rows),
            "registered_manifest_versions": count,
            "feature_snapshots_last_24h": fresh,
            "verified_feature_snapshots_last_24h": verified,
            "status": "BLOCKED" if len(reasons) else "READY",
            "reasons": reasons,
            "reviewed_identity_truth_independently_rechecked": False,
            "live_exact_line_probability_verified": False,
            "wagering_approved": False,
        }
    return {
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "scope": "NBA_NFL_NHL_SPORT_WIDE_READINESS_ONLY",
        "status": "BLOCKED",
        "sports": sport_rows,
        "provider_requests": 0,
        "database_writes": False,
        "betting_enabled": False,
        "notice": "Manifest presence and feature counts never prove current game/player joins or calibration.",
    }


def read_v7_readiness(store, models, *, observed_at=None):
    """Bounded read-only query against the existing indexed event store."""
    observed_at = observed_at or datetime.now(UTC)
    if observed_at.utcoffset() is None:
        raise ValueError("Aware observation time required")
    cutoff = observed_at.astimezone(UTC) - timedelta(hours=24)
    manifests = {}
    for label in SPORTS:
        # No record payload is printed or returned to the caller.
        manifests[label] = int(bool(store.list_records(
            "paid_player_identity_manifest", 1, entity=label
        )))
    with store.engine.connect() as conn:
        conn.execute(text("SET statement_timeout = '12000ms'"))
        rows = conn.execute(text("""
            SELECT payload->>'sport' AS sport,
                   COUNT(*) FILTER (WHERE occurred_at >= :cutoff) AS recent,
                   COUNT(*) FILTER (
                       WHERE occurred_at >= :cutoff
                         AND payload->>'production_inputs_verified' = 'true'
                         AND payload->>'research_only' = 'false'
                         AND (
                             COALESCE(payload->>'provider', '') NOT ILIKE '%sportsdataio%'
                             OR payload->>'provider_data_verified' = 'true'
                         )
                   ) AS recent_verified
            FROM platform_events
            WHERE kind = 'player_feature_snapshot'
            GROUP BY payload->>'sport'
        """), {"cutoff": cutoff}).mappings().all()
    features = {
        row["sport"]: {"recent": row["recent"], "recent_verified": row["recent_verified"]}
        for row in rows if row["sport"] in SPORTS.values()
    }
    return summarize_readiness(models, manifests, features, observed_at=observed_at)

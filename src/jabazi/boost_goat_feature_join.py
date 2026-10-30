"""Fail-closed exact-identity GOAT offer to JABBAZI feature-snapshot audit.

This module validates whether a licensed sportsbook offer can be paired with a
point-in-time model feature record. It NEVER estimates a probability or approves
a bet. Provider ID crosswalks must be explicit, versioned and independently
audited: matching names is not sufficient.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re

from jabazi.boost_goat_model_map import GOAT_TO_JABBAZI


def _positive_int(value):
    return type(value) is int and value > 0


def _line(value):
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    return result.normalize() if result.is_finite() and result >= 0 else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    return stamp.astimezone(UTC)


def audit_exact_model_inputs(sport, sportsbook_rows, feature_rows, *, observed_at):
    """Return counts only; never output raw vendor rows or player identities.

    Each feature row must have verified BALLDONTLIE player/game identifiers,
    an exact JABBAZI market, the exact sportsbook threshold, a frozen pregame
    feature timestamp and a nonempty model version. Ambiguity rejects the join.
    """
    if sport not in GOAT_TO_JABBAZI:
        raise ValueError("Unsupported sport")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Aware observation time required")
    now = observed_at.astimezone(UTC)
    reasons = Counter()
    index = {}
    duplicates = set()
    for row in feature_rows:
        if not isinstance(row, dict) or row.get("sport") != sport:
            reasons["feature_invalid_sport_or_schema"] += 1
            continue
        game, player = row.get("bdl_game_id"), row.get("bdl_player_id")
        market, threshold = row.get("jabbazi_market"), _line(row.get("line"))
        version, snapshot = row.get("model_version"), _timestamp(row.get("feature_frozen_at"))
        kickoff = _timestamp(row.get("event_starts_at"))
        crosswalk = row.get("identity_crosswalk_sha256")
        source = row.get("feature_source_sha256")
        snapshot_id = row.get("feature_snapshot_id")
        if (not _positive_int(game) or not _positive_int(player)
                or market not in GOAT_TO_JABBAZI[sport].values()
                or threshold is None or not isinstance(version, str)
                or not version.strip() or snapshot is None
                or not timedelta(0) <= now - snapshot <= timedelta(hours=48)
                or kickoff is None or not snapshot < kickoff
                or not isinstance(crosswalk, str) or not re.fullmatch(r"[0-9a-f]{64}", crosswalk)
                or not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{64}", source)
                or not isinstance(snapshot_id, str) or not re.fullmatch(r"playerfs-[0-9a-f]{20}", snapshot_id)
                or row.get("provider_identity_verified") is not True
                or row.get("pregame_snapshot_verified") is not True):
            reasons["feature_identity_or_pregame_evidence_missing"] += 1
            continue
        key = (game, player, market, threshold)
        if key in index:
            duplicates.add(key)
        else:
            index[key] = version
    for key in duplicates:
        del index[key]
    reasons["ambiguous_feature_records"] += len(duplicates)
    seen_offers = set()
    matched = 0
    for wrapper in sportsbook_rows:
        if not isinstance(wrapper, dict) or wrapper.get("sport") not in (
            sport, {"NBA":"basketball_nba","NFL":"americanfootball_nfl","NHL":"icehockey_nhl"}[sport]
        ):
            reasons["offer_wrong_sport_or_schema"] += 1
            continue
        raw = wrapper.get("raw")
        if not isinstance(raw, dict):
            reasons["offer_wrong_sport_or_schema"] += 1
            continue
        game, player = raw.get("game_id"), raw.get("player_id")
        market = GOAT_TO_JABBAZI[sport].get(raw.get("prop_type"))
        threshold = _line(raw.get("line_value"))
        stamp = _timestamp(raw.get("updated_at"))
        if (not _positive_int(game) or not _positive_int(player)
                or market is None or threshold is None or stamp is None
                or not timedelta(0) <= now - stamp <= timedelta(minutes=15)):
            reasons["offer_unmapped_stale_or_invalid"] += 1
            continue
        key = (game, player, market, threshold)
        vendor = raw.get("vendor")
        if not isinstance(vendor, str) or not vendor.strip():
            reasons["offer_unmapped_stale_or_invalid"] += 1
            continue
        offer_key = (key, vendor.strip().lower())
        if offer_key in seen_offers:
            reasons["duplicate_offer"] += 1
            continue
        seen_offers.add(offer_key)
        if key not in index:
            reasons["no_verified_exact_feature_match"] += 1
        else:
            matched += 1
    return {
        "sport": sport, "observed_at": now.isoformat(),
        "sportsbook_rows_received": len(sportsbook_rows),
        "feature_rows_received": len(feature_rows),
        "exact_versioned_input_matches": matched,
        "rejections": dict(sorted(reasons.items())),
        "model_probability_computed": False,
        "model_calibration_verified": False,
        "joint_probability_verified": False,
        "betting_enabled": False,
        "approval": "RESEARCH_ONLY",
    }

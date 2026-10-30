"""Research-only exact-line GOAT quote -> fitted JABBAZI distribution adapter.

Requires a separately reviewed cross-provider identity manifest, a real frozen
JABBAZI feature snapshot, and a versioned fitted player artifact. Never
uses sportsbook implied probability as the model estimate. Never approves
wagers or correlation/SGP EV; live acceptance is still required.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import math
import re

from jabazi.boost_goat_model_map import GOAT_TO_JABBAZI
from jabazi.boost_identity_manifest import SOURCE_NAMESPACE, crosswalk_digest
from jabazi.boost_offer_integrity import inspect_prop_offer
from jabazi.boost_scope import SPORTS
from jabazi.models.player_distribution import (
    PLAYER_PROP_MARKETS, calibrated_probability,
)
from jabazi.research.player_features import REQUIRED_INTEGRITY

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT = re.compile(r"^playerfs-[0-9a-f]{20}$")


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.utcoffset() is not None else None


def _positive(value):
    return type(value) is int and value > 0


def _valid_american(value):
    return type(value) is int and (value <= -100 or value >= 100)


def _line(value):
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() and number >= 0 else None


def research_goat_exact_line(sport, raw_offer, crosswalk, snapshot, artifact, *,
                             observed_at):
    """Return de-identified research estimates or a fail-closed reason code.

    A true attestation flag and valid SHA-256 *format* do not independently
    establish that the provider crosswalk is correct. That review is external.
    """
    if sport not in ("NBA", "NFL"):
        raise ValueError("Only NBA/NFL authenticated source research supported")
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        raise ValueError("Aware observation time required")
    now = observed_at.astimezone(UTC)
    base = {
        "sport": sport, "status": "UNAVAILABLE",
        "reason": "SOURCE_EVIDENCE_MISSING",
        "market": None, "line": None, "model_version": None,
        "research_probabilities": [],
        "independent_identity_review_confirmed_by_runtime": False,
        "calibration_independently_validated": False,
        "joint_probability_validated": False,
        "betting_enabled": False, "production_approved": False,
    }
    if not all(isinstance(x, dict) for x in (raw_offer, crosswalk, snapshot, artifact)):
        return base
    game_id, player_id = raw_offer.get("game_id"), raw_offer.get("player_id")
    if not _positive(game_id) or not _positive(player_id):
        base["reason"] = "INVALID_VENDOR_IDENTITIES"
        return base
    _, issue = inspect_prop_offer(raw_offer, game_id, observed_at=now)
    if issue is not None:
        base["reason"] = "INVALID_OR_STALE_SPORTSBOOK_OFFER"
        return base
    market = GOAT_TO_JABBAZI[sport].get(raw_offer.get("prop_type"))
    line = _line(raw_offer.get("line_value"))
    if market is None or line is None:
        base["reason"] = "UNSUPPORTED_EXACT_MARKET"
        return base
    base["market"], base["line"] = market, str(line)
    start = _stamp(snapshot.get("starts_at"))
    frozen = _stamp(snapshot.get("features_available_at"))
    reviewed = _stamp(crosswalk.get("reviewed_at"))
    crosswalk_start = _stamp(crosswalk.get("event_starts_at"))
    if (crosswalk.get("sport") != sport
            or crosswalk.get("bdl_game_id") != game_id
            or crosswalk.get("bdl_player_id") != player_id
            or crosswalk.get("source_namespace") != SOURCE_NAMESPACE[sport]
            or crosswalk.get("independent_source_reviewed") is not True
            or not isinstance(crosswalk.get("record_sha256"), str)
            or crosswalk["record_sha256"] != crosswalk_digest(crosswalk)
            or not isinstance(crosswalk.get("source_record_sha256"), str)
            or not _DIGEST.fullmatch(crosswalk["source_record_sha256"])
            or not isinstance(crosswalk.get("canonical_event_id"), str)
            or not crosswalk["canonical_event_id"]
            or not isinstance(crosswalk.get("source_player_id"), str)
            or not crosswalk["source_player_id"]
            or reviewed is None or start is None or frozen is None
            or crosswalk_start != start
            or not reviewed <= now < start
            or not now - timedelta(hours=1) <= frozen <= now
            or not frozen < start):
        base["reason"] = "IDENTITY_OR_PREGAME_PROVENANCE_UNVERIFIED"
        return base
    if (snapshot.get("sport") != SPORTS[sport]
            or snapshot.get("event_id") != crosswalk["canonical_event_id"]
            or str(snapshot.get("player_id")) != crosswalk["source_player_id"]
            or snapshot.get("market") != market
            or not isinstance(snapshot.get("snapshot_id"), str)
            or not _SNAPSHOT.fullmatch(snapshot["snapshot_id"])
            or not isinstance(snapshot.get("source_checksum"), str)
            or not _DIGEST.fullmatch(snapshot["source_checksum"])
            or not isinstance(snapshot.get("provider"), str)
            or not snapshot["provider"].strip()
            or not isinstance(snapshot.get("feature_schema_version"), str)
            or not snapshot["feature_schema_version"]
            or snapshot.get("research_only") is not False
            or snapshot.get("production_inputs_verified") is not True
            or ("sportsdataio" in str(snapshot.get("provider", "")).lower()
                and snapshot.get("provider_data_verified") is not True)
            or not isinstance(snapshot.get("integrity"), dict)
            or not all(snapshot["integrity"].get(k) is True for k in REQUIRED_INTEGRITY)):
        base["reason"] = "FROZEN_MODEL_FEATURE_INTEGRITY_UNVERIFIED"
        return base
    if (artifact.get("sport") != SPORTS[sport]
            or artifact.get("market") != market
            or artifact.get("artifact_type") != "player_prop_distribution"
            or market not in PLAYER_PROP_MARKETS[SPORTS[sport]]
            or artifact.get("stage") not in ("VALIDATING", "PRODUCTION_APPROVED")
            or not isinstance(artifact.get("model_version"), str)
            or not artifact["model_version"]):
        base["reason"] = "MODEL_ARTIFACT_NOT_SUPPORTED"
        return base
    base["model_version"] = artifact["model_version"]
    quote_market = raw_offer["market"]
    sides = (
        [side for side, price in (
            ("over", quote_market.get("over_odds")),
            ("under", quote_market.get("under_odds")),
        ) if _valid_american(price)]
        if quote_market.get("type") == "over_under" else
        ["yes"] if quote_market.get("type") == "milestone"
        and _valid_american(quote_market.get("odds")) else []
    )
    if not sides:
        base["reason"] = "NO_SUPPORTED_QUOTED_SIDE"
        return base
    features = snapshot.get("features")
    if not isinstance(features, dict):
        base["reason"] = "FROZEN_MODEL_FEATURE_INTEGRITY_UNVERIFIED"
        return base
    try:
        results = []
        for side in sides:
            p = float(calibrated_probability(artifact, features, side, line))
            if not math.isfinite(p) or not 0 < p < 1:
                raise ValueError("Invalid model output")
            results.append({"side": side, "research_probability": round(p, 10)})
    except (ValueError, TypeError, KeyError, ArithmeticError, OverflowError):
        base["reason"] = "EXACT_LINE_MODEL_INFERENCE_UNAVAILABLE"
        return base
    base.update({
        "status": "RESEARCH_ONLY",
        "reason": "UNAPPROVED_DISTRIBUTION_ESTIMATE",
        "research_probabilities": results,
    })
    return base

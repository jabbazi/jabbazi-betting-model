"""Private GOAT-to-JABBAZI exact-line research acceptance orchestrator.

Consumes real paid prop rows plus independently reviewed crosswalks, immutable
pregame feature snapshots, and versioned fitted artifacts. Output is aggregate
counts only. This code cannot independently prove crosswalk truth, validate
calibration, approve joint tickets, or authorize wagering.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime

from jabazi.boost_goat_model_map import GOAT_TO_JABBAZI
from jabazi.boost_goat_research_inference import research_goat_exact_line
from jabazi.boost_scope import SPORTS


def audit_exact_line_research(sport, offers, crosswalks, snapshots, artifacts, *,
                              observed_at):
    if sport not in ("NBA", "NFL"):
        raise ValueError("Only NBA/NFL source research is supported")
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        raise ValueError("Timezone-aware observation required")
    for rows in (offers, crosswalks, snapshots, artifacts):
        if not isinstance(rows, (list, tuple)) or len(rows) > 10000:
            raise ValueError("Bounded record lists required")

    reasons = Counter()
    crosswalk_index = defaultdict(list)
    snapshot_index = defaultdict(list)
    artifact_index = defaultdict(list)
    for row in crosswalks:
        if not isinstance(row, dict) or row.get("sport") != sport:
            reasons["CROSSWALK_INVALID_SCHEMA"] += 1
            continue
        game, player = row.get("bdl_game_id"), row.get("bdl_player_id")
        if type(game) is not int or game <= 0 or type(player) is not int or player <= 0:
            reasons["CROSSWALK_INVALID_ID"] += 1
            continue
        crosswalk_index[(game, player)].append(row)
    for row in snapshots:
        if not isinstance(row, dict) or row.get("sport") != SPORTS[sport]:
            reasons["SNAPSHOT_INVALID_SCHEMA"] += 1
            continue
        key = (row.get("event_id"), str(row.get("player_id")),
               row.get("market"))
        if not all(isinstance(x, str) and x for x in key):
            reasons["SNAPSHOT_INVALID_KEY"] += 1
            continue
        snapshot_index[key].append(row)
    for row in artifacts:
        if not isinstance(row, dict) or row.get("sport") != SPORTS[sport]:
            reasons["ARTIFACT_INVALID_SCHEMA"] += 1
            continue
        market = row.get("market")
        if not isinstance(market, str) or not market:
            reasons["ARTIFACT_INVALID_MARKET"] += 1
            continue
        artifact_index[market].append(row)

    seen = set()
    estimates = 0
    sides = 0
    versions = set()
    for wrapped in offers:
        if not isinstance(wrapped, dict) or wrapped.get("sport") != SPORTS[sport]:
            reasons["OFFER_WRONG_SPORT_OR_SCHEMA"] += 1
            continue
        raw = wrapped.get("raw")
        if not isinstance(raw, dict):
            reasons["OFFER_WRONG_SPORT_OR_SCHEMA"] += 1
            continue
        game, player = raw.get("game_id"), raw.get("player_id")
        if type(game) is not int or game <= 0 or type(player) is not int or player <= 0:
            reasons["OFFER_INVALID_ID"] += 1
            continue
        market = GOAT_TO_JABBAZI[sport].get(raw.get("prop_type"))
        if market is None:
            reasons["OFFER_UNMAPPED_MARKET"] += 1
            continue
        # Repeated vendor/market/line rows must never inflate acceptance.
        # The vendor quote ID is NOT sufficient as a deduplication key.
        key = (game, player, market, str(raw.get("line_value")),
               str(raw.get("vendor")), str(raw.get("market")))
        if key in seen:
            reasons["DUPLICATE_OFFER"] += 1
            continue
        seen.add(key)
        candidates = crosswalk_index.get((game, player), ())
        if len(candidates) != 1:
            reasons["MISSING_OR_AMBIGUOUS_CROSSWALK"] += 1
            continue
        crosswalk = candidates[0]
        feature_key = (crosswalk.get("canonical_event_id"),
                       str(crosswalk.get("source_player_id")), market)
        features = snapshot_index.get(feature_key, ())
        if len(features) != 1:
            reasons["MISSING_OR_AMBIGUOUS_FROZEN_FEATURES"] += 1
            continue
        models = artifact_index.get(market, ())
        if len(models) != 1:
            reasons["MISSING_OR_AMBIGUOUS_FITTED_MODEL"] += 1
            continue
        result = research_goat_exact_line(
            sport, raw, crosswalk, features[0], models[0],
            observed_at=observed_at,
        )
        if result["status"] != "RESEARCH_ONLY":
            reasons[result["reason"]] += 1
            continue
        estimates += 1
        sides += len(result["research_probabilities"])
        versions.add(result["model_version"])

    return {
        "sport": sport,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "paid_offer_rows_received": len(offers),
        "reviewed_crosswalk_rows_supplied": len(crosswalks),
        "frozen_feature_rows_supplied": len(snapshots),
        "fitted_artifacts_supplied": len(artifacts),
        "exact_line_research_estimates": estimates,
        "research_probability_sides": sides,
        "model_versions_observed": sorted(versions),
        "rejections": dict(sorted(reasons.items())),
        "crosswalk_truth_independently_confirmed_by_runtime": False,
        "prospective_calibration_verified": False,
        "joint_probability_verified": False,
        "betting_enabled": False,
        "production_approved": False,
        "status": "RESEARCH_ONLY" if estimates else "UNAVAILABLE",
    }

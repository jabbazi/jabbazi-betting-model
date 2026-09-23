"""Provider-neutral admission checks for future prop-model training datasets.

This validates evidence, not probabilities. No model is fitted or approved here.
Every feature vector must be a point-in-time snapshot, not a final-game box score.
"""

from collections import Counter
from datetime import UTC, datetime
import math


MARKETS = {
    "baseball_mlb": {"pitcher_strikeouts"},
    "americanfootball_nfl": {"player_pass_yds", "player_rush_yds", "player_reception_yds"},
}


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone-aware evidence required")
    return result.astimezone(UTC)


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Finite numeric feature/label required")
    return value


def inspect_prop_dataset(document, *, train_before, test_before, minimum_per_split=100):
    """Check a single sport/market dataset; boundaries must be chosen in advance.

    Manifest permissions are the owner's supplied evidence reference, not an
    independent legal verification. Passing admits internal research only.
    DNP/void records are excluded and counted, never relabeled as zero outcomes.
    """
    manifest = document.get("manifest", {})
    sport, market = manifest.get("sport"), manifest.get("market")
    if market not in MARKETS.get(sport, set()):
        raise ValueError("Unsupported prop target; anytime TD requires a separate dataset/model")
    if (
        manifest.get("data_mode") != "real"
        or not manifest.get("provider")
        or not manifest.get("source_checksum")
        or not manifest.get("research_rights_reference")
    ):
        raise ValueError("Real-data provenance and research permission evidence required")
    left, right = timestamp(train_before), timestamp(test_before)
    if left >= right or type(minimum_per_split) is not int or minimum_per_split < 1:
        raise ValueError("Invalid chronological split policy")
    seen, features = set(), None
    counts, excluded = Counter(), Counter()
    dates = {part: [] for part in ("train", "calibration", "test")}
    for row in document.get("rows", []):
        key = (row["event_id"], row["player_id"])
        if not all(key) or key in seen:
            raise ValueError("Duplicate or missing event/player identity")
        seen.add(key)
        decision, start = timestamp(row["prediction_at"]), timestamp(row["starts_at"])
        available, result_at = (
            timestamp(row["features_available_at"]),
            timestamp(row["result_available_at"]),
        )
        if not available <= decision < start <= result_at:
            raise ValueError("Future features or invalid result timing")
        part = "train" if decision < left else "calibration" if decision < right else "test"
        if (part == "train" and result_at >= left) or (
            part == "calibration" and result_at >= right
        ):
            raise ValueError("A training/calibration label crosses the next split boundary")
        status = row.get("result_status")
        if status in {"dnp", "void"}:
            excluded[status] += 1
            continue
        if status != "final":
            raise ValueError("Unresolved prop outcome")
        observed = finite(row["observed_value"])
        if market == "pitcher_strikeouts" and (observed < 0 or int(observed) != observed):
            raise ValueError("Strikeouts must be a nonnegative count")
        vector = row.get("features", {})
        if not vector or any(not isinstance(k, str) or not k for k in vector):
            raise ValueError("Named point-in-time feature vector required")
        if features is None:
            features = set(vector)
        if set(vector) != features:
            raise ValueError("Inconsistent feature schema")
        for value in vector.values():
            finite(value)
        # Explicit pregame usage estimate; no future actual snaps/pitches as exposure.
        if finite(row["expected_opportunities"]) < 0:
            raise ValueError("Invalid pregame usage estimate")
        counts[part] += 1
        dates[part].append(decision.isoformat())
    enough = all(counts[part] >= minimum_per_split for part in dates)
    return {
        "status": "READY_FOR_RESEARCH_FIT" if enough else "INSUFFICIENT_DATA",
        "approved_for_betting": False,
        "trained_model_available": False,
        "sport": sport,
        "market": market,
        "provider": manifest["provider"],
        "source_checksum": manifest["source_checksum"],
        "counts": {part: counts[part] for part in dates},
        "excluded": dict(excluded),
        "date_ranges": {
            part: [min(values), max(values)] if values else None for part, values in dates.items()
        },
        "features": sorted(features or []),
        "minimum_per_split": minimum_per_split,
        "note": "Admission counts are not statistical power or model-validation thresholds. "
        "Feature content/leakage, source rights and actual availability require audit. "
        "No probabilities, ROI, CLV, or production approval are inferred.",
    }

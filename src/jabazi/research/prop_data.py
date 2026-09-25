"""Provider-neutral admission checks for player-prop training datasets.

This validates evidence, not probabilities. Every feature vector must be a
point-in-time snapshot; DNP/void records are excluded rather than relabeled.
"""
from collections import Counter
from datetime import UTC, datetime
import math

from jabazi.models.player_distribution import (
    BINARY_MARKETS,
    COUNT_MARKETS,
    PLAYER_PROP_MARKETS,
)

MARKETS = PLAYER_PROP_MARKETS


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone-aware evidence required")
    return result.astimezone(UTC)


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Finite numeric feature/label required")
    return value


def _probability(value, label):
    if value is None:
        return None
    value = finite(value)
    if not 0 < value < 1:
        raise ValueError(f"{label} must be between zero and one")
    return value


def inspect_prop_dataset(document, *, train_before, test_before, minimum_per_split=100):
    """Check one sport/market dataset using predeclared chronological boundaries.

    Passing admits research fitting only. Production approval is a separate,
    prospective evidence decision.
    """
    manifest = document.get("manifest", {})
    sport, market = manifest.get("sport"), manifest.get("market")
    if market not in MARKETS.get(sport, set()):
        raise ValueError("Unsupported prop target")
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
    threshold_rows = Counter()
    market_baseline_rows = Counter()
    closing_rows = Counter()

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
        if observed < 0:
            raise ValueError("Player prop outcomes must be nonnegative")
        if market in COUNT_MARKETS and int(observed) != observed:
            raise ValueError("Count prop outcome must be an integer count")
        if market in BINARY_MARKETS and observed not in {0, 1}:
            raise ValueError("Binary prop outcome must be 0 or 1")

        vector = row.get("features", {})
        if not vector or any(not isinstance(k, str) or not k for k in vector):
            raise ValueError("Named point-in-time feature vector required")
        if features is None:
            features = set(vector)
        if set(vector) != features:
            raise ValueError("Inconsistent feature schema")
        for value in vector.values():
            finite(value)

        expected = finite(row["expected_opportunities"])
        if expected < 0:
            raise ValueError("Invalid pregame usage estimate")

        # Threshold-specific probability validation needs an actual pregame line.
        line = row.get("market_line")
        if line is not None:
            finite(line)
            side = str(row.get("market_side", "over")).lower()
            if side not in {"over", "under", "yes", "no"}:
                raise ValueError("Invalid market side")
            threshold_rows[part] += 1

        if _probability(row.get("market_no_vig_probability"), "market probability") is not None:
            market_baseline_rows[part] += 1
        if _probability(row.get("closing_no_vig_probability"), "closing probability") is not None:
            closing_rows[part] += 1

        integrity = row.get("integrity", {})
        if integrity and not isinstance(integrity, dict):
            raise ValueError("Integrity evidence must be a mapping")
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
        "threshold_rows": {part: threshold_rows[part] for part in dates},
        "market_baseline_rows": {part: market_baseline_rows[part] for part in dates},
        "closing_rows": {part: closing_rows[part] for part in dates},
        "excluded": dict(excluded),
        "date_ranges": {
            part: [min(values), max(values)] if values else None for part, values in dates.items()
        },
        "features": sorted(features or []),
        "minimum_per_split": minimum_per_split,
        "note": (
            "Admission counts are not validation thresholds. A fitted model remains research-only "
            "until held-out and frozen prospective probability/calibration/CLV gates pass."
        ),
    }

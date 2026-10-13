"""Prospective first-touchdown forecast evaluation; never grants betting approval.

Each input is a frozen, timestamped categorical forecast made before kickoff.
Actual outcomes must include defensive/special-teams and no-touchdown buckets
when applicable. Missing events are not counted as losses or zero probabilities.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite, log


class FirstTDValidationError(ValueError):
    pass


def _instant(value):
    if not isinstance(value, str):
        raise FirstTDValidationError("Timestamp required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FirstTDValidationError("Invalid timestamp") from exc
    if dt.tzinfo is None:
        raise FirstTDValidationError("Timezone-aware timestamp required")
    return dt


def fair_american(probability):
    p = float(probability)
    if not isfinite(p) or not 0 < p < 1:
        raise FirstTDValidationError("Fair odds require a probability strictly between zero and one")
    return round(100 * (1 - p) / p) if p <= 0.5 else round(-100 * p / (1 - p))


def evaluate_frozen_forecasts(records, *, minimum_games=100):
    """Evaluate only complete, strictly pre-event, unique game predictions.

    Each record: event_id, model_version, forecast_at, starts_at,
    actual (a categorical outcome key), probabilities (all outcome keys).
    These are retrospective metrics, not an authorization to publish wagers.
    """
    if not isinstance(records, (list, tuple)):
        raise FirstTDValidationError("Forecast collection required")
    if not isinstance(minimum_games, int) or minimum_games < 1:
        raise FirstTDValidationError("Invalid minimum sample")
    seen = set()
    versions = set()
    log_losses = []
    brier_scores = []
    correct = 0
    buckets = {i: {"n": 0, "sum_p": 0.0, "hits": 0} for i in range(10)}
    for row in records:
        if not isinstance(row, dict):
            raise FirstTDValidationError("Malformed forecast")
        event = str(row.get("event_id") or "")
        version = str(row.get("model_version") or "")
        if not event or not version or event in seen:
            raise FirstTDValidationError("Missing identity/version or duplicate game")
        seen.add(event)
        versions.add(version)
        if _instant(row.get("forecast_at")) >= _instant(row.get("starts_at")):
            raise FirstTDValidationError("Forecast must be frozen before kickoff")
        probabilities = row.get("probabilities")
        if not isinstance(probabilities, dict) or len(probabilities) < 3 or "NO_TD" not in probabilities or "OTHER_OR_DEFENSE_ST" not in probabilities:
            raise FirstTDValidationError("Complete categorical outcomes including NO_TD required")
        if not all(isinstance(key, str) and key for key in probabilities):
            raise FirstTDValidationError("Invalid outcome identity")
        try:
            values = {key: float(value) for key, value in probabilities.items()}
        except (TypeError, ValueError) as exc:
            raise FirstTDValidationError("Invalid probability") from exc
        if any(not isfinite(p) or p < 0 or p > 1 for p in values.values()):
            raise FirstTDValidationError("Invalid probability")
        if abs(sum(values.values()) - 1) > 1e-8:
            raise FirstTDValidationError("Outcome probabilities must sum to one")
        actual = row.get("actual")
        if actual not in values:
            raise FirstTDValidationError("Actual outcome is missing from forecast support")
        log_losses.append(-log(max(values[actual], 1e-15)))
        brier_scores.append(sum((p - int(key == actual)) ** 2 for key, p in values.items()))
        pick = max(values, key=values.get)
        confidence = values[pick]
        hit = int(pick == actual)
        correct += hit
        bucket = min(9, int(confidence * 10))
        buckets[bucket]["n"] += 1
        buckets[bucket]["sum_p"] += confidence
        buckets[bucket]["hits"] += hit
    n = len(records)
    calibration = [
        {"bucket": i, "count": v["n"],
         "mean_confidence": v["sum_p"] / v["n"],
         "hit_rate": v["hits"] / v["n"]}
        for i, v in buckets.items() if v["n"]
    ]
    return {
        "state": "RESEARCH_VALIDATION_ONLY" if n >= minimum_games else "INSUFFICIENT_SAMPLE",
        "approved_for_betting": False,
        "sample_count": n,
        "model_versions": sorted(versions),
        "multiclass_log_loss": sum(log_losses) / n if n else None,
        "multiclass_brier_score": sum(brier_scores) / n if n else None,
        "top_outcome_accuracy": correct / n if n else None,
        "top_outcome_calibration": calibration,
        "notice": "Out-of-sample chronology, representative coverage, market comparison and independent review are still required before betting approval.",
    }

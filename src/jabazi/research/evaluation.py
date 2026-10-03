"""Chronological evaluation and held-out isotonic calibration primitives."""

from dataclasses import dataclass
from datetime import datetime
import math
from statistics import mean


@dataclass(frozen=True)
class Observation:
    probability: float
    outcome: int
    predicted_at: datetime
    starts_at: datetime
    result_available_at: datetime
    model_version: str

    def __post_init__(self):
        if (
            not math.isfinite(self.probability)
            or not 0 <= self.probability <= 1
            or self.outcome not in (0, 1)
        ):
            raise ValueError("Invalid prediction/outcome")
        if any(
            x.tzinfo is None for x in (self.predicted_at, self.starts_at, self.result_available_at)
        ):
            raise ValueError("Timezone-aware timestamps required")
        if not self.predicted_at < self.starts_at <= self.result_available_at:
            raise ValueError("Prediction timing would leak results")
        if not self.model_version:
            raise ValueError("Model version required")


def chronological_split(rows, train_before, calibrate_before):
    if train_before >= calibrate_before:
        raise ValueError("Invalid split boundaries")
    ordered = sorted(rows, key=lambda r: r.predicted_at)
    train = [
        r for r in ordered if r.predicted_at < train_before and r.result_available_at < train_before
    ]
    calibration = [
        r
        for r in ordered
        if train_before <= r.predicted_at < calibrate_before
        and r.result_available_at < calibrate_before
    ]
    test = [r for r in ordered if r.predicted_at >= calibrate_before]
    if not all((train, calibration, test)):
        raise ValueError("Each chronological split needs observations")
    return train, calibration, test


def evaluate(rows):
    if not rows:
        raise ValueError("No observations")
    p = [r.probability for r in rows]
    y = [r.outcome for r in rows]
    bins = []
    for i in range(10):
        indices = [j for j, x in enumerate(p) if min(int(x * 10), 9) == i]
        if indices:
            bins.append(
                {
                    "lower": i / 10,
                    "upper": (i + 1) / 10,
                    "n": len(indices),
                    "mean_probability": mean(p[j] for j in indices),
                    "observed_rate": mean(y[j] for j in indices),
                }
            )
    pos = [x for x, o in zip(p, y) if o]
    neg = [x for x, o in zip(p, y) if not o]
    auc = (
        (
            sum(1 if a > b else 0.5 if a == b else 0 for a in pos for b in neg)
            / (len(pos) * len(neg))
        )
        if pos and neg
        else None
    )
    return {
        "n": len(rows),
        "brier": mean((a - b) ** 2 for a, b in zip(p, y)),
        "log_loss": -mean(
            b * math.log(max(a, 1e-12)) + (1 - b) * math.log(max(1 - a, 1e-12))
            for a, b in zip(p, y)
        ),
        "roc_auc": auc,
        "reliability": bins,
        "expected_calibration_error": sum(
            b["n"] / len(rows) * abs(b["mean_probability"] - b["observed_rate"]) for b in bins
        ),
    }


@dataclass(frozen=True)
class IsotonicCalibration:
    blocks: tuple[tuple[float, float, float], ...]
    fitted_at: datetime
    model_version: str

    def predict(self, p, at, model_version):
        if not 0 <= p <= 1 or not math.isfinite(p):
            raise ValueError("Invalid probability")
        if at < self.fitted_at or model_version != self.model_version:
            raise ValueError("Calibration version/time mismatch")
        for lower, upper, value in self.blocks:
            if p <= upper:
                return value
        return self.blocks[-1][2]


def fit_isotonic(calibration_rows, *, fitted_at, minimum_samples=100):
    if len(calibration_rows) < minimum_samples:
        raise ValueError("Insufficient calibration sample")
    if any(r.result_available_at >= fitted_at for r in calibration_rows):
        raise ValueError("Future result in calibration")
    versions = {r.model_version for r in calibration_rows}
    if len(versions) != 1:
        raise ValueError("Calibrate one model version at a time")
    grouped = {}
    for r in calibration_rows:
        count, total = grouped.get(r.probability, (0, 0))
        grouped[r.probability] = (count + 1, total + r.outcome)
    blocks = []
    for p, (count, total) in sorted(grouped.items()):
        blocks.append([p, p, total, count])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            b = blocks.pop()
            a = blocks.pop()
            blocks.append([a[0], b[1], a[2] + b[2], a[3] + b[3]])
    return IsotonicCalibration(
        tuple((a, b, total / count) for a, b, total, count in blocks), fitted_at, versions.pop()
    )

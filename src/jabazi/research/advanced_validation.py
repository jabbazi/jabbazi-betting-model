"""Advanced validation statistics and model evidence cards.

Dependency-light helpers used by research/admin jobs. They never promote a model
by themselves; callers must apply the configured gate policy.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import math
import random
from statistics import mean
from typing import Callable, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class EvidenceCard:
    model: str
    version: str
    stage: str
    raw_n: int
    effective_n: float
    prospective_days: int
    brier: float | None = None
    log_loss: float | None = None
    ece: float | None = None
    mean_clv_prob_points: float | None = None
    clv_ci: tuple[float, float] | None = None
    roi: float | None = None
    roi_ci: tuple[float, float] | None = None
    data_coverage: float | None = None
    drift_status: str = "UNKNOWN"
    passed_gates: tuple[str, ...] = ()
    failed_gates: tuple[str, ...] = ()
    blocking_gate: str | None = None
    next_review: str | None = None

    def as_dict(self):
        return asdict(self)


def cluster_effective_sample_size(rows: Sequence[Mapping], cluster_keys=("event_id",)) -> float:
    """Conservative Kish-style effective N using cluster sizes as weights.

    Perfectly correlated observations inside a cluster contribute no more than
    one cluster's worth of independent evidence. This is deliberately
    conservative until a richer correlation estimator is validated.
    """
    if not rows:
        return 0.0
    counts = defaultdict(int)
    for row in rows:
        key = tuple(row.get(k) for k in cluster_keys)
        counts[key] += 1
    weights = list(counts.values())
    return (sum(weights) ** 2) / sum(w * w for w in weights)


def cluster_bootstrap_ci(
    rows: Sequence[Mapping],
    statistic: Callable[[Sequence[Mapping]], float],
    *,
    cluster_keys=("event_id",),
    confidence=0.95,
    iterations=2000,
    seed=0,
):
    """Cluster bootstrap confidence interval with deterministic default seed."""
    if not rows:
        raise ValueError("rows required")
    if not 0 < confidence < 1 or iterations < 100:
        raise ValueError("invalid bootstrap configuration")
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(k) for k in cluster_keys)].append(row)
    clusters = list(groups.values())
    rng = random.Random(seed)
    values = []
    for _ in range(iterations):
        sample = []
        for _ in range(len(clusters)):
            sample.extend(clusters[rng.randrange(len(clusters))])
        value = float(statistic(sample))
        if math.isfinite(value):
            values.append(value)
    if not values:
        raise ValueError("statistic produced no finite bootstrap values")
    values.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = values[max(0, min(len(values) - 1, int(alpha * len(values))))]
    hi = values[max(0, min(len(values) - 1, int((1.0 - alpha) * len(values)) - 1))]
    return lo, hi


def mean_field(field):
    def statistic(rows):
        vals = [float(row[field]) for row in rows if row.get(field) is not None]
        if not vals:
            raise ValueError(f"no values for {field}")
        return mean(vals)
    return statistic


def calibration_bucket_status(effective_n: float, minimum_effective_n: int = 50) -> str:
    return "MEANINGFUL" if effective_n >= minimum_effective_n else "INSUFFICIENT_SAMPLE"


def promotion_gate_matrix(gates: Mapping[str, bool], critical_gates: Iterable[str]):
    failed = tuple(sorted(name for name, passed in gates.items() if not passed))
    passed = tuple(sorted(name for name, ok in gates.items() if ok))
    critical_failed = tuple(sorted(name for name in critical_gates if not gates.get(name, False)))
    return {
        "eligible": not failed,
        "passed": passed,
        "failed": failed,
        "critical_failed": critical_failed,
        "blocking_gate": critical_failed[0] if critical_failed else (failed[0] if failed else None),
    }

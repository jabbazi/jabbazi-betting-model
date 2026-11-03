"""Chronological calibration experiments. Never fits on evaluation labels."""

import math
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


def _design(p, method):
    p = np.clip(np.asarray(p, dtype=float), 1e-8, 1 - 1e-8)
    if method == "platt":
        return np.log(p / (1 - p)).reshape(-1, 1)
    if method == "beta":
        return np.column_stack([np.log(p), -np.log1p(-p)])
    raise ValueError("Unknown calibrator")


def fit(p, y, method):
    if len(p) < 100 or len(set(y)) < 2:
        raise ValueError("Insufficient calibration outcomes")
    if method == "isotonic":
        return IsotonicRegression(out_of_bounds="clip").fit(p, y)
    # Nonnegative beta coefficients checked before admission to preserve monotonicity.
    model = LogisticRegression(C=1.0, max_iter=1000).fit(_design(p, method), y)
    if any(v < 0 for v in model.coef_[0]):
        raise ValueError("Non-monotonic calibration rejected")
    return model


def transform(model, p, method):
    return (
        model.predict(p) if method == "isotonic" else model.predict_proba(_design(p, method))[:, 1]
    )


def wilson(wins, n):
    if not n:
        return [None, None]
    z = 1.96
    p = wins / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [center - half, center + half]


def report(p, y):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=int)
    if len(p) == 0:
        return {"n": 0, "brier": None, "log_loss": None, "buckets": []}
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any() or not set(y).issubset({0, 1}):
        raise ValueError("Invalid calibration sample")
    buckets = []
    bounds = [
        0,
        0.05,
        0.10,
        0.15,
        0.20,
        0.25,
        0.30,
        0.35,
        0.40,
        0.45,
        0.50,
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
        0.80,
        0.85,
        1.000000001,
    ]
    for lo, hi in zip(bounds, bounds[1:]):
        mask = (p >= lo) & (p < hi)
        n = int(mask.sum())
        wins = int(y[mask].sum())
        buckets.append(
            dict(
                lower=lo,
                upper=min(hi, 1),
                n=n,
                mean_probability=float(p[mask].mean()) if n else None,
                observed_rate=wins / n if n else None,
                hit_rate_interval_95=wilson(wins, n),
            )
        )
    slope = intercept = None
    if len(set(y)) == 2 and np.std(p) > 1e-8:
        model = LogisticRegression(C=1e6, max_iter=1000).fit(_design(p, "platt"), y)
        slope = float(model.coef_[0, 0])
        intercept = float(model.intercept_[0])
    # Deterministic bootstrap intervals are descriptive; game-clustered when one row/game.
    rng = np.random.default_rng(20260925)
    losses = (p - y) ** 2
    means = [float(losses[rng.integers(len(p), size=len(p))].mean()) for _ in range(300)]
    return dict(
        n=len(p),
        brier=float(brier_score_loss(y, p)),
        log_loss=float(log_loss(y, np.clip(p, 1e-8, 1 - 1e-8), labels=[0, 1])),
        brier_interval_95=np.quantile(means, [0.025, 0.975]).tolist(),
        calibration_slope=slope,
        calibration_intercept=intercept,
        roc_auc=float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
        ece=sum(b["n"] * abs(b["mean_probability"] - b["observed_rate"]) for b in buckets if b["n"])
        / len(p),
        buckets=buckets,
    )

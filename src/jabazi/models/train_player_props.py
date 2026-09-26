"""Chronological fitting and promotion logic for player-prop distribution models.

Historical backtests can advance a model to VALIDATING/LIMITED_LIVE research states.
PRODUCTION_APPROVED requires separate frozen prospective evidence; a backtest cannot
self-promote a betting model.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import math

from .player_distribution import (
    BINARY_MARKETS,
    CONTINUOUS_MARKETS,
    COUNT_MARKETS,
    PLAYER_PROP_MARKETS,
    raw_probability,
)
from jabazi.research.prop_data import inspect_prop_dataset, timestamp


def _clip(p):
    return min(1 - 1e-9, max(1e-9, float(p)))


def _brier(probabilities, outcomes):
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(outcomes)


def _log_loss(probabilities, outcomes):
    return -sum(y * math.log(_clip(p)) + (1-y) * math.log(1-_clip(p))
                for p, y in zip(probabilities, outcomes)) / len(outcomes)


def _ece(probabilities, outcomes, bins=10):
    total = len(outcomes)
    score = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        selected = [
            (p, y) for p, y in zip(probabilities, outcomes)
            if low <= p < high or (index == bins - 1 and p == 1)
        ]
        if not selected:
            continue
        confidence = sum(p for p, _ in selected) / len(selected)
        observed = sum(y for _, y in selected) / len(selected)
        score += len(selected) / total * abs(confidence - observed)
    return score


def _calibration_slope_intercept(probabilities, outcomes):
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:
        raise RuntimeError("Install project research dependencies") from exc
    if len(set(outcomes)) < 2:
        return None, None
    logits = np.asarray([[math.log(_clip(p) / (1-_clip(p)))] for p in probabilities])
    fit = LogisticRegression(C=1e6, solver="lbfgs", max_iter=2000).fit(logits, outcomes)
    return float(fit.coef_[0][0]), float(fit.intercept_[0])


def _constant_logit(probability):
    probability = _clip(probability)
    return math.log(probability / (1 - probability))


def _matrix(rows, names, means=None, scales=None):
    import numpy as np
    raw = np.asarray([[float(row["features"][name]) for name in names] for row in rows], dtype=float)
    if means is None:
        means = raw.mean(axis=0)
    if scales is None:
        scales = raw.std(axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    return (raw - means) / scales, means, scales


def _base_artifact(document, rows, market):
    manifest = document["manifest"]
    names = sorted(rows[0]["features"])
    x, means, scales = _matrix(rows, names)
    return {
        "artifact_type": "player_prop_distribution",
        "sport": manifest["sport"],
        "market": market,
        "provider": manifest["provider"],
        "source_checksum": manifest["source_checksum"],
        "feature_names": names,
        "scaler": {"mean": means.tolist(), "scale": scales.tolist()},
        "trained_at": datetime.now(UTC).isoformat(),
        "training_cutoff": max(timestamp(row["prediction_at"]) for row in rows).isoformat(),
        "stage": "SHADOW_ONLY",
    }, x


def _fit_family(document, training_rows, market):
    import numpy as np
    try:
        from sklearn.linear_model import LogisticRegression, PoissonRegressor, Ridge
    except ImportError as exc:
        raise RuntimeError("Install project research dependencies") from exc

    artifact, x = _base_artifact(document, training_rows, market)
    y = np.asarray([float(row["observed_value"]) for row in training_rows], dtype=float)

    if market in BINARY_MARKETS:
        binary = (y > 0).astype(int)
        if len(set(binary.tolist())) == 1:
            params = {
                "coef": [0.0] * x.shape[1],
                "intercept": _constant_logit(float(binary.mean())),
            }
        else:
            model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000).fit(x, binary)
            params = {"coef": model.coef_[0].tolist(), "intercept": float(model.intercept_[0])}
        artifact.update(family="binary_logistic", parameters=params)

    elif market in COUNT_MARKETS:
        if y.min() < 0:
            raise ValueError("Count prop cannot have negative outcomes")
        if y.mean() <= 0:
            params = {"coef": [0.0] * x.shape[1], "intercept": math.log(1e-6), "dispersion": 0.0}
        else:
            model = PoissonRegressor(alpha=0.5, max_iter=2000).fit(x, y)
            mu = np.maximum(model.predict(x), 1e-8)
            numerator = np.sum((y - mu) ** 2 - mu)
            denominator = np.sum(mu ** 2)
            dispersion = max(0.0, float(numerator / denominator)) if denominator else 0.0
            params = {
                "coef": model.coef_.tolist(),
                "intercept": float(model.intercept_),
                "dispersion": min(dispersion, 10.0),
            }
        artifact.update(family="count_nb", parameters=params)

    elif market in CONTINUOUS_MARKETS:
        # NFL yardage can legitimately be negative, so a signed residual
        # distribution is required.  Ridge supplies the conditional mean;
        # held-out residual scale supplies threshold probabilities.
        model = Ridge(alpha=2.0).fit(x, y)
        residual = y - model.predict(x)
        sigma = max(1.0, float(np.sqrt(np.mean(residual ** 2))))
        artifact.update(
            family="normal_ridge",
            parameters={
                "coef": model.coef_.tolist(),
                "intercept": float(model.intercept_),
                "sigma": sigma,
            },
        )
    else:
        raise ValueError("Unsupported player prop market")
    return artifact


def _threshold_rows(rows, artifact):
    result = []
    for row in rows:
        line = row.get("market_line")
        side = str(row.get("market_side", "over")).lower()
        if artifact["market"] in BINARY_MARKETS:
            line = 0.5 if line is None else line
            side = "yes" if side in {"over", "yes"} else "no"
        if line is None or side not in {"over", "under", "yes", "no"}:
            continue
        raw = raw_probability(artifact, row["features"], side, line)
        observed = float(row["observed_value"])
        if side in {"over", "yes"}:
            outcome = int(observed > float(line)) if artifact["market"] not in BINARY_MARKETS else int(observed > 0)
        else:
            outcome = int(observed < float(line)) if artifact["market"] not in BINARY_MARKETS else int(observed <= 0)
        result.append((row, raw, outcome))
    return result


def _fit_calibration(artifact, calibration_rows):
    threshold = _threshold_rows(calibration_rows, artifact)
    if len(threshold) < 100 or len({outcome for _, _, outcome in threshold}) < 2:
        return None
    try:
        import numpy as np
        from sklearn.isotonic import IsotonicRegression
    except ImportError as exc:
        raise RuntimeError("Install project research dependencies") from exc
    x = np.asarray([raw for _, raw, _ in threshold])
    y = np.asarray([outcome for _, _, outcome in threshold])
    model = IsotonicRegression(out_of_bounds="clip").fit(x, y)
    return {"method": "isotonic", "x": model.X_thresholds_.tolist(), "y": model.y_thresholds_.tolist()}


def _apply_calibration(raw, calibration):
    if not calibration:
        return raw
    from bisect import bisect_right
    x, y = calibration["x"], calibration["y"]
    index = min(len(y)-1, max(0, bisect_right(x, raw)-1))
    return float(y[index])


def _distribution_validation(artifact, test_rows):
    """Evaluate the fitted outcome distribution even when historical prop lines are absent.

    This can justify VALIDATING research status, never betting approval.
    """
    if not test_rows:
        return {"n": 0, "mae": None, "rmse": None, "mean_bias": None}
    from .player_distribution import distribution_mean

    errors = []
    binary_probabilities = []
    binary_outcomes = []
    for row in test_rows:
        mean, _ = distribution_mean(artifact, row["features"])
        observed = float(row["observed_value"])
        errors.append(mean - observed)
        if artifact["market"] in BINARY_MARKETS:
            binary_probabilities.append(float(mean))
            binary_outcomes.append(int(observed > 0))
    n = len(errors)
    result = {
        "n": n,
        "mae": sum(abs(e) for e in errors) / n,
        "rmse": math.sqrt(sum(e * e for e in errors) / n),
        "mean_bias": sum(errors) / n,
    }
    if binary_probabilities:
        result.update(
            brier=_brier(binary_probabilities, binary_outcomes),
            log_loss=_log_loss(binary_probabilities, binary_outcomes),
            ece=_ece(binary_probabilities, binary_outcomes),
        )
    return result


def _validation(artifact, test_rows):
    threshold = _threshold_rows(test_rows, artifact)
    if not threshold:
        return {
            "test_sample_count": 0,
            "promotion_passed": False,
            "reason": "No threshold-specific test evidence",
        }
    probabilities = [_apply_calibration(raw, artifact.get("calibration")) for _, raw, _ in threshold]
    outcomes = [outcome for _, _, outcome in threshold]
    slope, intercept = _calibration_slope_intercept(probabilities, outcomes)
    baselines = [
        float(row.get("market_no_vig_probability"))
        for row, _, _ in threshold
        if row.get("market_no_vig_probability") is not None
    ]
    baseline_brier = None
    baseline_log_loss = None
    if len(baselines) == len(threshold):
        baseline_brier = _brier(baselines, outcomes)
        baseline_log_loss = _log_loss(baselines, outcomes)

    edge_clv = []
    for row, probability, _ in [(r, probabilities[i], o) for i, (r, _, o) in enumerate(threshold)]:
        market = row.get("market_no_vig_probability")
        close = row.get("closing_no_vig_probability")
        if market is not None and close is not None and probability >= float(market) + 0.02:
            edge_clv.append(100 * (float(close) - float(market)))

    return {
        "test_sample_count": len(outcomes),
        "brier": _brier(probabilities, outcomes),
        "log_loss": _log_loss(probabilities, outcomes),
        "ece": _ece(probabilities, outcomes),
        "calibration_slope": slope,
        "calibration_intercept": intercept,
        "market_baseline_brier": baseline_brier,
        "market_baseline_log_loss": baseline_log_loss,
        "clv_edge_sample_count": len(edge_clv),
        "mean_clv_prob_points": sum(edge_clv) / len(edge_clv) if edge_clv else None,
        "prospective_sample_count": 0,
        "promotion_passed": False,
        "reason": "Historical/held-out evidence only; frozen prospective promotion required",
    }


def fit_prop_model(document, *, train_before, test_before, minimum_per_split=100):
    inspection = inspect_prop_dataset(
        document,
        train_before=train_before,
        test_before=test_before,
        minimum_per_split=minimum_per_split,
    )
    if inspection["status"] != "READY_FOR_RESEARCH_FIT":
        raise ValueError("Insufficient admitted prop data")
    sport, market = inspection["sport"], inspection["market"]
    if market not in PLAYER_PROP_MARKETS.get(sport, frozenset()):
        raise ValueError("Unsupported prop market")
    left, right = timestamp(train_before), timestamp(test_before)
    admitted = [
        row for row in document["rows"]
        if row.get("result_status") == "final"
    ]
    train = [
        row for row in admitted
        if timestamp(row["prediction_at"]) < left
        and timestamp(row["result_available_at"]) < left
    ]
    calibration = [
        row for row in admitted
        if left <= timestamp(row["prediction_at"]) < right
        and timestamp(row["result_available_at"]) < right
    ]
    test = [
        row for row in admitted
        if timestamp(row["prediction_at"]) >= right
    ]
    artifact = _fit_family(document, train, market)
    artifact["calibration"] = _fit_calibration(artifact, calibration)
    artifact["distribution_validation"] = _distribution_validation(artifact, test)
    artifact["validation"] = _validation(artifact, test)
    # The version identifies the fitted probability function, not the wall-clock
    # time of the training job. Identical fitted artifacts therefore keep one
    # version so frozen prospective evidence can accumulate across redeploys.
    version_payload = {
        "artifact_schema_version": 2,
        "sport": sport,
        "market": market,
        "family": artifact["family"],
        "feature_names": artifact["feature_names"],
        "scaler": artifact["scaler"],
        "parameters": artifact["parameters"],
        "calibration": artifact.get("calibration"),
        "train_before": left.isoformat(),
        "test_before": right.isoformat(),
    }
    seed = json.dumps(version_payload, sort_keys=True, separators=(",", ":"))
    artifact["artifact_schema_version"] = 2
    artifact["split_policy"] = {
        "train_before": left.isoformat(),
        "test_before": right.isoformat(),
    }
    artifact["model_version"] = (
        f"{sport.split('_')[-1]}-{market}-dist-0.2.0-"
        + hashlib.sha256(seed.encode()).hexdigest()[:12]
    )
    artifact["stage"] = (
        "VALIDATING"
        if artifact["distribution_validation"]["n"] >= 250
        else "SHADOW_ONLY"
    )
    if artifact["stage"] == "VALIDATING" and artifact["validation"]["test_sample_count"] == 0:
        artifact["validation"]["reason"] = (
            "Outcome distribution has held-out sample support; archived market-line "
            "calibration is unavailable, so betting approval remains blocked"
        )
    return artifact


def promotion_decision(artifact, prospective):
    """Promote only from honest distribution + frozen priced prospective evidence.

    Historical archives often lack sportsbook prop lines. In that case they can
    validate the outcome distribution, but they cannot prove betting edge. The
    market-relative/calibration/CLV gates therefore come from immutable prospective
    priced forecasts. Historical line-level evidence, when it exists, is an
    additional gate rather than a fabricated requirement.
    """
    candidate = deepcopy(artifact)
    historical = candidate.get("validation", {})
    distribution = candidate.get("distribution_validation", {})
    p = prospective or {}

    historical_priced_available = (
        int(historical.get("test_sample_count", 0) or 0) >= 500
        and historical.get("market_baseline_brier") is not None
    )
    historical_priced_ok = True
    if historical_priced_available:
        historical_priced_ok = (
            historical.get("brier") is not None
            and historical["brier"] < historical["market_baseline_brier"]
            and historical.get("ece") is not None
            and historical["ece"] <= 0.04
            and historical.get("calibration_slope") is not None
            and 0.80 <= historical["calibration_slope"] <= 1.20
        )

    checks = {
        "distribution_n": int(distribution.get("n", 0) or 0) >= 500,
        "historical_priced_if_available": historical_priced_ok,
        "prospective_n": int(p.get("sample_count", 0) or 0) >= 500,
        "prospective_brier_vs_market": (
            p.get("brier") is not None
            and p.get("market_baseline_brier") is not None
            and float(p["brier"]) + 0.002 < float(p["market_baseline_brier"])
        ),
        "prospective_ece": p.get("ece") is not None and float(p["ece"]) <= 0.04,
        "prospective_clv": (
            p.get("mean_clv_prob_points") is not None
            and int(p.get("clv_sample_count", 0) or 0) >= 150
            and float(p["mean_clv_prob_points"]) >= 0
        ),
        "data_health": int(p.get("data_health_failures", 1) or 0) == 0,
    }

    if all(checks.values()):
        stage = "PRODUCTION_APPROVED"
    elif (
        checks["distribution_n"]
        and checks["historical_priced_if_available"]
        and int(p.get("sample_count", 0) or 0) >= 200
        and p.get("brier") is not None
        and p.get("market_baseline_brier") is not None
        and float(p["brier"]) < float(p["market_baseline_brier"])
        and p.get("ece") is not None
        and float(p["ece"]) <= 0.06
        and checks["data_health"]
    ):
        stage = "LIMITED_LIVE"
    elif int(distribution.get("n", 0) or 0) >= 250:
        stage = "VALIDATING"
    else:
        stage = "SHADOW_ONLY"

    candidate["stage"] = stage
    candidate["validation"] = {
        **historical,
        "historical_priced_evidence_available": historical_priced_available,
        "prospective_sample_count": int(p.get("sample_count", 0) or 0),
        "prospective_brier": p.get("brier"),
        "prospective_market_baseline_brier": p.get("market_baseline_brier"),
        "prospective_ece": p.get("ece"),
        "prospective_mean_clv_prob_points": p.get("mean_clv_prob_points"),
        "promotion_checks": checks,
        "promotion_passed": stage == "PRODUCTION_APPROVED",
        "reason": (
            "Held-out distribution and all frozen prospective pricing/calibration/CLV gates passed"
            if stage == "PRODUCTION_APPROVED"
            else "Promotion gates incomplete; model remains research-limited"
        ),
    }
    return candidate

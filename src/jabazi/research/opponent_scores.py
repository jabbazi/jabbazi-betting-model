"""Offline opponent-adjusted team score challenger; no registry or promotion writes.

Every monthly fold separates fitting, residual estimation, joint calibration and
evaluation. Historical availability is a two-day proxy, not original receipts.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge

from jabazi.models.score_distribution import available_at, score_samples
from jabazi.models.team_elo import timestamp
from jabazi.research.train_scores import training_rows
from jabazi.research.rolling_upgrade import predictions, labels
from jabazi.research.calibration_report import report as calibration_report

PROTOCOL = {
    "version": "opponent-joint-score-0.1.0", "ridge_alpha": 20.0,
    "half_life_days": {"nfl": 365, "mlb": 180, "cfb": 240},
    "window_games": {"nfl": 120, "mlb": 300, "cfb": 160},
    "covariance_diagonal_shrinkage": .1, "diagnostic_season": 2025,
    "reserved_seasons": "2026 onward excluded from features and fitting",
    "selection": "fixed protocol; no tuning on diagnostic outcomes",
}


def matched_baseline(row, frozen):
    if any(row["game"][k] != frozen["game"][k] for k in (
        "game_id", "starts_at", "home_team", "away_team", "home_score", "away_score"
    )):
        raise ValueError("Frozen baseline game identity/result mismatch")
    if frozen["fold"] != row["game"]["starts_at"][:7]:
        raise ValueError("Frozen baseline fold mismatch")
    return frozen["raw"]


def split_fold(rows, cutoff, window):
    prior = [r for r in rows if available_at(r["game"]) < cutoff]
    if len(prior) < 2 * window + 100:
        raise ValueError("Insufficient chronological history")
    first = timestamp(prior[-2 * window]["game"]["starts_at"][:10] + "T00:00:00Z")
    second = timestamp(prior[-window]["game"]["starts_at"][:10] + "T00:00:00Z")
    train = [r for r in prior if available_at(r["game"]) < first]
    residual = [r for r in prior if first <= timestamp(r["game"]["starts_at"])
                and available_at(r["game"]) < second]
    calibrate = [r for r in prior if second <= timestamp(r["game"]["starts_at"])]
    if min(map(len, (train, residual, calibrate))) < 100:
        raise ValueError("Insufficient disjoint fold windows")
    return train, residual, calibrate


def design(rows, teams):
    index = {t: i for i, t in enumerate(teams)}
    matrix = np.zeros((2 * len(rows), 2 * len(teams) + 2))
    for i, row in enumerate(rows):
        g = row["game"]
        home, away = g["home_team"], g["away_team"]
        if home not in index or away not in index or home == away:
            raise ValueError("Unknown or invalid team identity")
        for j, (offense, defense, sign) in enumerate(((home, away, 1), (away, home, -1))):
            matrix[2*i+j, index[offense]] = 1
            matrix[2*i+j, len(teams)+index[defense]] = 1
            matrix[2*i+j, -2] = sign * float(not g["neutral_site"])
            matrix[2*i+j, -1] = sign * row["features"][4] / 7
    return matrix


def fit_scores(rows, cutoff, sport):
    if any(available_at(r["game"]) >= cutoff for r in rows):
        raise ValueError("Future label in model fitting")
    teams = sorted({r["game"][side+"_team"] for r in rows for side in ("home", "away")})
    target = [r["game"][side+"_score"] for r in rows for side in ("home", "away")]
    age = np.array([(cutoff-timestamp(r["game"]["starts_at"])).days for r in rows])
    weights = np.repeat(np.exp(-np.log(2)*age/PROTOCOL["half_life_days"][sport]), 2)
    model = Ridge(alpha=PROTOCOL["ridge_alpha"]).fit(design(rows, teams), target, sample_weight=weights)
    return teams, model


def residual_pairs(rows, teams, model):
    actual = np.array([[r["game"]["home_score"], r["game"]["away_score"]] for r in rows])
    return actual-model.predict(design(rows, teams)).reshape(-1, 2)


def joint_calibrate(residuals, calibration_errors):
    """One affine transformation of paired scores preserves a joint distribution.

    Fit mean and covariance on a later disjoint residual window. This calibrates
    joint moments, not a guarantee of probability calibration or correct tails.
    """
    arrays = [np.asarray(x, dtype=float) for x in (residuals, calibration_errors)]
    if any(x.ndim != 2 or x.shape[1] != 2 or len(x) < 100 or not np.isfinite(x).all() for x in arrays):
        raise ValueError("Need two finite paired-error windows with 100 games each")
    source, target = arrays
    cov = np.cov(source, rowvar=False)
    target_cov = np.cov(target, rowvar=False)
    shrink = PROTOCOL["covariance_diagonal_shrinkage"]
    target_cov = (1-shrink)*target_cov + shrink*np.diag(np.diag(target_cov))
    def root(matrix, power):
        values, vectors = np.linalg.eigh(matrix)
        if np.min(values) <= 1e-8:
            raise ValueError("Degenerate residual covariance")
        return (vectors * values**power) @ vectors.T
    adjusted = (source-source.mean(axis=0)) @ root(cov, -.5) @ root(target_cov, .5) + target.mean(axis=0)
    return adjusted


def samples(means, residuals):
    if not np.isfinite(means).all() or not np.isfinite(residuals).all():
        raise ValueError("Nonfinite score parameters")
    return np.maximum(0, np.floor(means + residuals + .5)).astype(int)


def run(source, output, sport):
    raw = Path(source).read_bytes()
    payload = json.loads(raw)
    # Filter before feature construction: never touch reserved-season outcomes.
    payload["games"] = [g for g in payload["games"] if int(g["season"]) <= 2025]
    rows = training_rows(payload, sport)
    baseline_bytes = (Path(__file__).parents[1]/"models/artifacts"/f"{sport}_scores.json").read_bytes()
    baseline = json.loads(baseline_bytes)
    baseline_rows = {r["game"]["game_id"]: r for r in training_rows(payload, sport, baseline.get("feature_policy"))}
    frozen_baseline = None
    if sport == "cfb":
        # The bundled CFB artifact is the final rolling fold, not a pre-2025 fit.
        # Use each game's frozen rolling prediction instead of leaking that fit.
        path = Path(__file__).parents[3]/"docs/experiments/reliability-upgrade/cfb/predictions.json.gz"
        with gzip.open(path, "rt") as stream:
            frozen_baseline = {r["game"]["game_id"]: r for r in json.load(stream)["recency_ridge"]}
    evaluated = [r for r in rows if r["game"]["season"] == 2025]
    periods = sorted({r["game"]["starts_at"][:7] for r in evaluated})
    forecasts, folds = [], []
    last_artifact = None
    for period in periods:
        test = [r for r in evaluated if r["game"]["starts_at"].startswith(period)]
        cutoff = min(timestamp(r["game"]["starts_at"]) for r in test)
        train, residual, cal = split_fold(rows, cutoff, PROTOCOL["window_games"][sport])
        teams, model = fit_scores(train, cutoff, sport)
        covered = lambda r: all(r["game"][s+"_team"] in teams for s in ("home", "away"))
        residual, cal = [r for r in residual if covered(r)], [r for r in cal if covered(r)]
        residuals = residual_pairs(residual, teams, model)
        calibrated = joint_calibrate(residuals, residual_pairs(cal, teams, model))
        eligible = [r for r in test if covered(r) and r["game"]["game_id"] in baseline_rows
                    and (frozen_baseline is None or r["game"]["game_id"] in frozen_baseline)]
        means = model.predict(design(eligible, teams)).reshape(-1, 2)
        fold = {"period": period, "train_n": len(train), "residual_n": len(residual),
                "calibration_n": len(cal), "evaluation_n": len(eligible),
                "unavailable_n": len(test)-len(eligible), "prediction_start": cutoff.isoformat(),
                "train_last_label": max(available_at(r["game"]) for r in train).isoformat(),
                "residual_first_start": min(r["game"]["starts_at"] for r in residual),
                "residual_last_label": max(available_at(r["game"]) for r in residual).isoformat(),
                "calibration_first_start": min(r["game"]["starts_at"] for r in cal),
                "calibration_last_label": max(available_at(r["game"]) for r in cal).isoformat()}
        folds.append(fold)
        for row, mean in zip(eligible, means, strict=True):
            g = row["game"]
            draws = {"opponent": samples(mean, residuals),
                     "joint_calibrated_opponent": samples(mean, calibrated)}
            probabilities = {name: predictions(s, sport) for name,s in draws.items()}
            probabilities["baseline"] = (matched_baseline(row, frozen_baseline[g["game_id"]]) if frozen_baseline is not None
                else predictions(score_samples(baseline, baseline_rows[g["game_id"]]["features"]), sport))
            forecasts.append({"game_id": g["game_id"], "starts_at": g["starts_at"], "fold": period,
                "labels": labels(g, sport), "probabilities": probabilities,
                "predicted_scores": mean.tolist(), "features": row["features"],
                "home_team": g["home_team"], "away_team": g["away_team"]})
        last_artifact = {"teams": teams, "coefficients": model.coef_.tolist(), "intercept": float(model.intercept_),
            "residual_pairs": calibrated.tolist(), "fold": fold}
    if not forecasts:
        raise ValueError("No diagnostic coverage")
    metrics = {}
    for name in ("baseline", "opponent", "joint_calibrated_opponent"):
        metrics[name] = {}
        for market in forecasts[0]["labels"]:
            eligible = [f for f in forecasts if f["labels"][market] is not None]
            metrics[name][market] = calibration_report(
                [f["probabilities"][name][market] for f in eligible], [f["labels"][market] for f in eligible])
    from jabazi.research.player_prospective import _event_comparison
    comparison = {}
    for name in ("opponent", "joint_calibrated_opponent"):
        comparison[name] = {}
        for market in forecasts[0]["labels"]:
            grouped = {}
            for f in forecasts:
                y = f["labels"][market]
                if y is None:
                    continue
                delta = (f["probabilities"][name][market]-y)**2 - (f["probabilities"]["baseline"][market]-y)**2
                # Week blocks retain temporal dependence across games better than row resampling.
                iso = timestamp(f["starts_at"]).isocalendar()
                grouped.setdefault(f"{iso.year}-{iso.week:02}", []).append(delta)
            block_report = _event_comparison(grouped)
            block_report["week_blocks"] = block_report.pop("independent_events")
            block_report["method"] = "equal-ISO-week-weight-bootstrap-400-v1"
            comparison[name][market] = block_report | {"cluster_unit": "ISO_week"}
    document = {"protocol": PROTOCOL, "sport": sport, "source_sha256": hashlib.sha256(raw).hexdigest(),
                "baseline_artifact_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
                "baseline_forecasts_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if frozen_baseline is not None else None,
                "training_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "status": "RESEARCH_ONLY", "approved_for_betting": False, "folds": folds,
                "metrics": metrics, "paired_comparison": comparison, "roi": None, "clv": None,
                "limitations": ["Previously inspected 2025 data: diagnostic, not untouched final holdout",
                    "Two-day availability proxy, no original point-in-time receipts",
                    "No QB, starter, injury, lineup, usage or weather inputs",
                    "Fixed thresholds, not historical offered prices; no price-relative edge claim",
                    "Conditional decisive-game moneyline; simulated ties are not a verified overtime model",
                    "No player props; no CFB player props; no automatic registry or deployment writes"]}
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    (out/"report.json").write_text(json.dumps(document, indent=2, allow_nan=False)+"\n")
    artifact = {"protocol": PROTOCOL, "sport": sport, "source_sha256": document["source_sha256"],
                "status": "RESEARCH_ONLY", "approved_for_betting": False, **last_artifact}
    (out/"artifact.json").write_text(json.dumps(artifact, indent=2, allow_nan=False)+"\n")
    with (out/"predictions.json.gz").open("wb") as destination:
        with gzip.GzipFile(fileobj=destination, mode="wb", mtime=0) as stream:
            stream.write(json.dumps(forecasts, allow_nan=False).encode())
    print(json.dumps({"sport": sport, "games": len(forecasts), "brier": {
        name: {m: round(v["brier"],6) for m,v in values.items()} for name,values in metrics.items()}}), flush=True)
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sport", choices=("nfl", "mlb", "cfb"))
    parser.add_argument("source"); parser.add_argument("output")
    args = parser.parse_args()
    run(args.source, args.output, args.sport)

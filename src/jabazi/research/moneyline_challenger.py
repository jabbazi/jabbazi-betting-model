"""Offline, chronological NFL/MLB moneyline experiment; never a live promotion.

2021–22 fit -> 2023 select -> refit through 2023 -> 2024 Platt calibration ->
already-inspected 2025 diagnostic. No 2026 outcome is admitted to this experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from jabazi.models.score_distribution import FEATURES, available_at, outcome_probability, score_samples
from jabazi.models.team_elo import market_probability, replay, timestamp, validate_history
from jabazi.research.model_audit import calibration_summary
from jabazi.research.train_scores import bucket_metrics, training_rows

PROTOCOL = {
    "version": "moneyline-challenger-0.1.0",
    "selection_year": 2023,
    "calibration_year": 2024,
    "diagnostic_year": 2025,
    "families": ["form", "form_elo"],
    "regularization_c": [0.1, 1.0, 10.0],
    "selection_metric": "log_loss",
    "calibration": "logistic_on_logit_C1",
    "elo": {"nfl": [24.0, 0.0, 0.75], "mlb": [16.0, 0.0, 0.85]},
    "bootstrap": {"group": "UTC ISO calendar week", "replicates": 1000, "seed": 20260923},
}


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def logit(p):
    p = min(1 - 1e-8, max(1e-8, float(p)))
    return math.log(p / (1 - p))


def feature_rows(payload, sport):
    if sport not in PROTOCOL["elo"]:
        raise ValueError("Only NFL and MLB are supported")
    # Validate input before filtering, but never build state from excluded outcomes.
    admitted = [g for g in validate_history(payload, sport) if 2021 <= g["season"] <= 2025]
    eligible = dict(payload, games=admitted)
    _, ratings = replay(admitted, *PROTOCOL["elo"][sport])
    prior = {g["game_id"]: logit(p) for g, p, _ in ratings}
    output = []
    for row in training_rows(eligible, sport):
        g = row["game"]
        output.append({
            "game": g,
            "form": row["features"],
            "form_elo": row["features"] + [prior[g["game_id"]]],
            "outcome": None if g["home_score"] == g["away_score"]
            else int(g["home_score"] > g["away_score"]),
        })
    return output, admitted


def partitions(rows):
    groups = {
        "fit": [r for r in rows if r["game"]["season"] < 2023 and r["outcome"] is not None],
        "selection": [r for r in rows if r["game"]["season"] == 2023 and r["outcome"] is not None],
        "calibration": [r for r in rows if r["game"]["season"] == 2024 and r["outcome"] is not None],
        "diagnostic": [r for r in rows if r["game"]["season"] == 2025 and r["outcome"] is not None],
    }
    for name, group in groups.items():
        if len(group) < 100 or {r["outcome"] for r in group} != {0, 1}:
            raise ValueError(f"Need 100 decisive observations and both classes in {name}")
    values = list(groups.values())
    for left, right in zip(values, values[1:]):
        if max(available_at(r["game"]) for r in left) >= min(timestamp(r["game"]["starts_at"]) for r in right):
            raise ValueError("Result availability crosses a split boundary")
    return groups


def fit(rows, family, c):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=2000, random_state=0))
    return model.fit([r[family] for r in rows], [r["outcome"] for r in rows])


def predict(model, rows, family):
    return model.predict_proba([r[family] for r in rows])[:, 1]


def summarize(rows, probabilities):
    from sklearn.metrics import roc_auc_score

    pairs = [(float(p), r["outcome"]) for r, p in zip(rows, probabilities, strict=True)]
    result = bucket_metrics(pairs)
    result.update(calibration_summary(result))
    result["roc_auc"] = float(roc_auc_score([y for p, y in pairs], [p for p, y in pairs])) if len({y for p, y in pairs}) == 2 else None
    return result


def paired_comparison(rows, candidate, reference):
    """Paired losses on the same games; weekly resampling is descriptive only."""
    import numpy as np

    paired = [(r, float(p), float(q)) for r, p, q in zip(rows, candidate, reference, strict=True) if q is not None]
    groups = defaultdict(list)
    for row, p, q in paired:
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (p, q)):
            raise ValueError("Invalid paired probability")
        y = row["outcome"]
        week = timestamp(row["game"]["starts_at"]).isocalendar()[:2]
        ll = lambda v: -(y * math.log(max(v, 1e-12)) + (1 - y) * math.log(max(1 - v, 1e-12)))
        groups[week].append(((p - y) ** 2 - (q - y) ** 2, ll(p) - ll(q)))
    result = {
        "n": len(paired), "week_blocks": len(groups),
        "candidate": summarize([r for r, p, q in paired], [p for r, p, q in paired]),
        "reference": summarize([r for r, p, q in paired], [q for r, p, q in paired]),
        "difference": None,
        "note": "Negative favors candidate. Descriptive weekly bootstrap; not evidence of profitability or independent prospective validation.",
    }
    if not paired:
        return result
    totals = np.array([np.sum(group, axis=0) for group in groups.values()])
    counts = np.array([len(group) for group in groups.values()])
    delta = totals.sum(axis=0) / counts.sum()
    interval = None
    if len(groups) >= 10:
        rng = np.random.default_rng(PROTOCOL["bootstrap"]["seed"])
        draws = rng.integers(0, len(groups), size=(PROTOCOL["bootstrap"]["replicates"], len(groups)))
        sample = totals[draws].sum(axis=1) / counts[draws].sum(axis=1)[:, None]
        interval = np.quantile(sample, [0.025, 0.975], axis=0)
    result["difference"] = {name: {
        "mean": float(delta[i]),
        "weekly_bootstrap_95_percent_interval": interval[:, i].tolist() if interval is not None else None,
    } for i, name in enumerate(("brier", "log_loss"))}
    return result


def train(source, output, sport, score_artifact_path):
    import numpy as np
    import sklearn
    from sklearn.linear_model import LogisticRegression

    raw = Path(source).read_bytes()
    payload = json.loads(raw)
    rows, admitted = feature_rows(payload, sport)
    split = partitions(rows)
    trials = []
    for family in PROTOCOL["families"]:
        for c in PROTOCOL["regularization_c"]:
            model = fit(split["fit"], family, c)
            metrics = summarize(split["selection"], predict(model, split["selection"], family))
            trials.append({"family": family, "c": c, "selection": metrics})
    winner = min(trials, key=lambda trial: (trial["selection"]["log_loss"], trial["family"], trial["c"]))
    family = winner["family"]
    refit = split["fit"] + split["selection"]
    model = fit(refit, family, winner["c"])
    calibration, diagnostic = split["calibration"], split["diagnostic"]
    calibrator = LogisticRegression(C=1.0, max_iter=2000, random_state=0).fit(
        [[logit(p)] for p in predict(model, calibration, family)], [r["outcome"] for r in calibration])
    uncalibrated = predict(model, diagnostic, family)
    calibrated = calibrator.predict_proba([[logit(p)] for p in uncalibrated])[:, 1]

    # Score-model comparator uses frozen coefficients/residuals, not its current team state.
    score_raw = Path(score_artifact_path).read_bytes()
    baseline = json.loads(score_raw)
    if baseline["sport"] != payload["sport"] or baseline["source_checksum"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("Score comparator source or sport does not match")
    score_probs = []
    for row in diagnostic:
        g = row["game"]
        p = outcome_probability(score_samples(baseline, row["form"]), "h2h", g["home_team"], None, g["home_team"], g["away_team"])
        score_probs.append(p["win"] / (p["win"] + p["loss"]) if p["win"] + p["loss"] else None)
    market_probs = [market_probability(r["game"]) for r in diagnostic]
    # Historical labels are not execution evidence; these files have no verified quotes.
    version = f"{sport}-{PROTOCOL['version']}-{checksum({'protocol': PROTOCOL, 'games': admitted})[:12]}"
    scaler, fitted = model.steps[0][1], model.steps[1][1]
    artifact = {
        "schema_version": 1, "sport": payload["sport"], "model_version": version,
        "status": "RESEARCH_ONLY", "approved_for_betting": False,
        "supported_markets": ["h2h_decisive_game_only"],
        "family": family, "c": winner["c"],
        "features": list(FEATURES) + (["lagged_elo_logit"] if family == "form_elo" else []),
        "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
        "coefficients": fitted.coef_[0].tolist(), "intercept": float(fitted.intercept_[0]),
        "calibration_slope": float(calibrator.coef_[0][0]),
        "calibration_intercept": float(calibrator.intercept_[0]),
        "admitted_games_sha256": checksum(admitted), "protocol_sha256": checksum(PROTOCOL),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }
    predictions = [{
        "game_id": r["game"]["game_id"], "starts_at": r["game"]["starts_at"],
        "season": r["game"]["season"], "outcome": r["outcome"],
        "model_version": version, "probability": float(p), "uncalibrated_probability": float(u),
        "score_reference_probability": score, "market_probability": market,
        "market_timestamp_verified": False,
    } for r, p, u, score, market in zip(diagnostic, calibrated, uncalibrated, score_probs, market_probs, strict=True)]
    report = {
        "model_version": version, "status": "RESEARCH_ONLY", "approved_for_betting": False,
        "protocol": PROTOCOL, "protocol_sha256": checksum(PROTOCOL),
        "source_sha256": artifact["source_sha256"], "admitted_games_sha256": checksum(admitted),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "score_comparator_sha256": hashlib.sha256(score_raw).hexdigest(),
        "dependencies": {"numpy": np.__version__, "sklearn": sklearn.__version__},
        "split_counts": {name: len(group) for name, group in split.items()},
        "excluded_post_2025_games": sum(g["season"] > 2025 for g in payload["games"]),
        "excluded_ties_with_features": sum(r["outcome"] is None for r in rows),
        "selection_trials": trials, "selected": {"family": family, "c": winner["c"]},
        "diagnostic_uncalibrated": summarize(diagnostic, uncalibrated),
        "diagnostic_calibrated": summarize(diagnostic, calibrated),
        "paired_score_reference": paired_comparison(diagnostic, calibrated, score_probs),
        "paired_market_reference": paired_comparison(diagnostic, calibrated, market_probs),
        "execution_backtest": {"available": False, "roi": None, "clv": None, "reason": "No decision-time-verified historical prices"},
        "limitations": [
            "2025 was already inspected; this is development diagnostics, not an untouched test",
            "2026 outcomes excluded entirely; no prospective evidence is produced by this run",
            "Score/form/Elo features only: no verified pitcher/QB/lineup/usage/injury/weather inputs",
            "Two-UTC-day result availability is a proxy, not provider publication timestamps",
            "NFL moneyline probabilities condition on a decisive result; tie/void settlement not modeled",
            "Weekly bootstrap does not remove all team/time dependence or multiple-experiment bias",
            "Commercial data and derived-output rights still require confirmation",
            "No live registry change, production approval, staking or automated promotion",
        ],
    }
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (("artifact", artifact), ("report", report), ("diagnostic_predictions", predictions)):
        (out / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sport", choices=("nfl", "mlb"))
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--score-artifact", required=True)
    args = parser.parse_args()
    result = train(args.source, args.output, args.sport, args.score_artifact)
    print(json.dumps({k: result[k] for k in ("model_version", "selected", "split_counts", "diagnostic_calibrated")}))

"""Offline NFL scoring-form challenger. No live registry or betting authorization.

Fixed experiment: train through 2023, calibrate 2024, diagnose on already-viewed
2025. Preserve 2026 for prospective work. Results become available two UTC date
boundaries after kickoff, matching the documented conservative baseline policy.
"""

import argparse
import hashlib
import json
import math
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jabazi.models.team_elo import market_probability, timestamp, validate_history
from jabazi.research.evaluation import Observation, evaluate

FEATURES = (
    "home_scoring_form",
    "away_scoring_form",
    "home_conceding_form",
    "away_conceding_form",
    "rest_advantage_days",
    "home_field",
)
VERSION = "nfl-scoring-form-logistic-0.1.0"


def available_at(row):
    day = timestamp(row["starts_at"]).date() + timedelta(days=2)
    return datetime.combine(day, datetime.min.time(), UTC)


def feature_rows(payload):
    rows = validate_history(payload, "nfl")
    history = defaultdict(lambda: deque(maxlen=8))
    pending, output = [], []
    for row in rows:
        start = timestamp(row["starts_at"])
        ready = [r for r in pending if available_at(r) < start]
        pending = [r for r in pending if available_at(r) >= start]
        for previous in ready:
            for side, other in (("home", "away"), ("away", "home")):
                history[previous[f"{side}_team"]].append(
                    (
                        previous[f"{side}_score"],
                        previous[f"{other}_score"],
                        timestamp(previous["starts_at"]),
                        available_at(previous),
                    )
                )
        home, away = history[row["home_team"]], history[row["away_team"]]
        # Explicit minimum coverage; new teams cannot receive made-up form estimates.
        if len(home) >= 4 and len(away) >= 4:
            form = lambda games, column: sum(g[column] for g in games) / len(games)
            rest_h = min(21, max(0, (start - home[-1][2]).total_seconds() / 86400))
            rest_a = min(21, max(0, (start - away[-1][2]).total_seconds() / 86400))
            output.append(
                {
                    "game": row,
                    "features": [
                        form(home, 0),
                        form(away, 0),
                        form(home, 1),
                        form(away, 1),
                        rest_h - rest_a,
                        float(not row["neutral_site"]),
                    ],
                    "feature_available_at": max(g[3] for g in (*home, *away)).isoformat(),
                    "outcome": None
                    if row["home_score"] == row["away_score"]
                    else int(row["home_score"] > row["away_score"]),
                }
            )
        pending.append(row)
    return output


def logit(p):
    p = min(1 - 1e-8, max(1e-8, float(p)))
    return math.log(p / (1 - p))


def scored(rows, probabilities):
    return evaluate(
        [
            Observation(
                float(p),
                r["outcome"],
                timestamp(r["game"]["starts_at"]) - timedelta(microseconds=1),
                timestamp(r["game"]["starts_at"]),
                available_at(r["game"]),
                VERSION,
            )
            for r, p in zip(rows, probabilities, strict=True)
        ]
    )


def train(source, output_dir):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    raw = Path(source).read_bytes()
    payload = json.loads(raw)
    # Deliberately do not consume reserved 2026 outcomes, even for feature updates.
    eligible = dict(payload, games=[g for g in payload["games"] if g["season"] <= 2025])
    generated = feature_rows(eligible)
    decisive = [r for r in generated if r["outcome"] is not None]
    training = [r for r in decisive if r["game"]["season"] <= 2023]
    calibration = [r for r in decisive if r["game"]["season"] == 2024]
    diagnostic = [r for r in decisive if r["game"]["season"] == 2025]
    if min(map(len, (training, calibration, diagnostic))) < 100:
        raise ValueError("Need at least 100 decisive observations in every split")
    first_cal = min(timestamp(r["game"]["starts_at"]) for r in calibration)
    first_test = min(timestamp(r["game"]["starts_at"]) for r in diagnostic)
    if any(available_at(r["game"]) >= first_cal for r in training):
        raise ValueError("Training labels unavailable at calibration boundary")
    if any(available_at(r["game"]) >= first_test for r in calibration):
        raise ValueError("Calibration labels unavailable at diagnostic boundary")
    scaler = StandardScaler().fit([r["features"] for r in training])
    model = LogisticRegression(C=1.0, max_iter=2000, random_state=0)
    model.fit(scaler.transform([r["features"] for r in training]), [r["outcome"] for r in training])

    def predict(rows):
        return model.predict_proba(scaler.transform([r["features"] for r in rows]))[:, 1]

    calibrator = LogisticRegression(C=1.0, max_iter=2000, random_state=0)
    calibrator.fit([[logit(p)] for p in predict(calibration)], [r["outcome"] for r in calibration])
    uncalibrated = predict(diagnostic)
    calibrated = calibrator.predict_proba([[logit(p)] for p in uncalibrated])[:, 1]
    paired = [
        (r, p, market_probability(r["game"]))
        for r, p in zip(diagnostic, calibrated, strict=True)
        if market_probability(r["game"]) is not None
    ]
    report = {
        "model_version": VERSION,
        "status": "RESEARCH_ONLY",
        "approved_for_betting": False,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "split_counts": {
            "training_through_2023": len(training),
            "calibration_2024": len(calibration),
            "diagnostic_2025": len(diagnostic),
        },
        "reserved_2026_rows_not_used": sum(g["season"] == 2026 for g in payload["games"]),
        "ties_excluded": sum(r["outcome"] is None for r in generated),
        "uncalibrated": scored(diagnostic, uncalibrated),
        "calibrated": scored(diagnostic, calibrated),
        "training_home_rate_reference": scored(
            diagnostic, np.full(len(diagnostic), np.mean([r["outcome"] for r in training]))
        ),
        "paired_market_diagnostic": {
            "model": scored([r for r, p, m in paired], [p for r, p, m in paired])
            if paired
            else None,
            "market": scored([r for r, p, m in paired], [m for r, p, m in paired])
            if paired
            else None,
            "timestamp_verified_prices": sum(
                bool(r["game"].get("odds_observed_at"))
                and timestamp(r["game"]["odds_observed_at"]) < timestamp(r["game"]["starts_at"])
                for r, p, m in paired
            ),
        },
        "limitations": [
            "2025 was previously inspected: diagnostic only, not an untouched final holdout",
            "Score-only features: no EPA, QB, injury, lineup, weather or player usage inputs",
            "No point-in-time historical odds simulation, realized ROI or proven betting edge",
            "Two-UTC-day result delay is a proxy, not actual provider availability evidence",
            "Decisive-game probabilities exclude ties and are not a three-way settlement model",
            "Calibration is not model approval; prospective evidence and stronger features remain required",
        ],
    }
    artifact = {
        "model_version": VERSION,
        "status": "RESEARCH_ONLY",
        "approved_for_betting": False,
        "features": FEATURES,
        "training_mean": scaler.mean_.tolist(),
        "training_scale": scaler.scale_.tolist(),
        "coefficients": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "calibration_slope": float(calibrator.coef_[0][0]),
        "calibration_intercept": float(calibrator.intercept_[0]),
        "source_sha256": report["source_sha256"],
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (("artifact.json", artifact), ("report.json", report)):
        (out / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    predictions = [
        {
            "game_id": r["game"]["game_id"],
            "starts_at": r["game"]["starts_at"],
            "feature_available_at": r["feature_available_at"],
            "probability": float(p),
            "outcome": r["outcome"],
            "model_version": VERSION,
        }
        for r, p in zip(diagnostic, calibrated, strict=True)
    ]
    (out / "diagnostic_predictions.json").write_text(json.dumps(predictions, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    result = train(args.source, args.output_dir)
    print(
        json.dumps(
            {
                "status": result["status"],
                "counts": result["split_counts"],
                "calibrated_brier": result["calibrated"]["brier"],
            }
        )
    )

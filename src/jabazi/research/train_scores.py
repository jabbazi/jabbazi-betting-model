"""Reproducible NFL/MLB score-distribution experiments. Never a model approval."""

import argparse
import hashlib
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from jabazi.models.score_distribution import (
    FEATURES,
    available_at,
    features,
    outcome_probability,
    score_samples,
    state_from_games,
)
from jabazi.models.team_elo import SPORTS, market_probability, metrics, timestamp, validate_history


def training_rows(payload, sport, feature_policy=None):
    window, minimum = (8, 4) if sport in {"nfl", "cfb"} else (20, 10)
    state, pending, output = {}, deque(), []
    for game in validate_history(payload, sport):
        start = timestamp(game["starts_at"])
        while pending and available_at(pending[0]) < start:
            previous = pending.popleft()
            for side, other in (("home", "away"), ("away", "home")):
                team = previous[f"{side}_team"]
                state.setdefault(team, []).append(
                    [
                        previous[f"{side}_score"],
                        previous[f"{other}_score"],
                        previous["starts_at"],
                        available_at(previous).isoformat(),
                        previous[f"{other}_team"],
                    ]
                )
                state[team] = state[team][-window:]
        vector = features(
            state, game["home_team"], game["away_team"], start, game["neutral_site"], minimum, feature_policy
        )
        if vector is not None:
            output.append({"game": game, "features": vector})
        pending.append(game)
    return output


def bucket_metrics(pairs):
    result = metrics(pairs)
    result["reliability"] = []
    for i in range(10):
        subset = [(p, y) for p, y in pairs if i / 10 <= p < (i + 1) / 10 or (i == 9 and p == 1)]
        result["reliability"].append(
            {
                "lower": i / 10,
                "n": len(subset),
                "mean_probability": sum(p for p, y in subset) / len(subset) if subset else None,
                "observed_rate": sum(y for p, y in subset) / len(subset) if subset else None,
            }
        )
    return result


def train(source, output, sport, *, now=None):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    now = now or datetime.now(UTC)
    raw = Path(source).read_bytes()
    payload = json.loads(raw)
    all_games = validate_history(payload, sport)
    # 2026 updates current feature state only; no use in fitting/tuning/evaluation.
    rows = training_rows(payload | {"games": [g for g in all_games if g["season"] <= 2025]}, sport)
    fitting = [r for r in rows if r["game"]["season"] <= 2023]
    calibration = [r for r in rows if r["game"]["season"] == 2024]
    diagnostic = [r for r in rows if r["game"]["season"] == 2025]
    if min(len(fitting), len(calibration), len(diagnostic)) < 100:
        raise ValueError("Insufficient chronological split coverage")
    for left, right in ((fitting, calibration), (calibration, diagnostic)):
        if max(available_at(r["game"]) for r in left) >= min(
            timestamp(r["game"]["starts_at"]) for r in right
        ):
            raise ValueError("Labels cross chronological split boundary")
    scaler = StandardScaler().fit([r["features"] for r in fitting])
    model = Ridge(alpha=100.0).fit(
        scaler.transform([r["features"] for r in fitting]),
        [[r["game"]["home_score"], r["game"]["away_score"]] for r in fitting],
    )
    residuals = np.array(
        [[r["game"]["home_score"], r["game"]["away_score"]] for r in calibration]
    ) - model.predict(scaler.transform([r["features"] for r in calibration]))
    checksum = hashlib.sha256(raw).hexdigest()
    version = f"{sport}-score-ridge-0.1.0-{checksum[:12]}"
    artifact = {
        "schema_version": 1,
        "sport": SPORTS[sport],
        "model_name": f"{sport}_paired_score_research",
        "model_version": version,
        "status": "SHADOW_ONLY",
        "approved_for_betting": False,
        "features": list(FEATURES),
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coefficients": model.coef_.tolist(),
        "intercepts": model.intercept_.tolist(),
        "residual_pairs": residuals.tolist(),
        "source_checksum": checksum,
        "trained_at": now.isoformat(),
        "state_refreshed_at": now.isoformat(),
        "window": 8 if sport == "nfl" else 20,
        "minimum_games": 4 if sport == "nfl" else 10,
        "team_state": state_from_games(all_games, now=now, window=8 if sport == "nfl" else 20),
        "events": [],
        "history_provider": payload.get("provider"),
        "limitations": [
            "Research only: no evidence of a profitable betting edge or production approval",
            "Score/rest/home-field features only; no verified QB, starter, pitcher, lineup, injury or weather features",
            "Paired calibration residuals approximate score distributions; no player-prop or SGP model",
            "2025 already inspected previously; diagnostic, not untouched final holdout",
            "Historical result availability uses a two-UTC-date delay proxy",
            "No decision-time odds backtest, realized ROI, or CLV evidence",
            "Moneyline probability conditional on decisive game; integer-line pushes not integrated",
            "0.08 uncertainty haircut is a conservative policy setting, not an estimated confidence interval",
            "Internal research; provider commercial-use permissions require review before monetization",
        ],
    }
    threshold = 44.5 if sport == "nfl" else 8.5
    spread = -3.5 if sport == "nfl" else -1.5
    results = {key: [] for key in ("moneyline", "spread", "total")}
    reference = {key: [] for key in results}
    pooled = [(r["game"]["home_score"], r["game"]["away_score"]) for r in calibration]
    for row in diagnostic:
        g = row["game"]
        h, a = g["home_score"], g["away_score"]
        samples = score_samples(artifact, row["features"])
        for key, market, selection, line, outcome in (
            ("moneyline", "h2h", g["home_team"], None, float(h > a)),
            ("spread", "spreads", g["home_team"], spread, float(h - a + spread > 0)),
            ("total", "totals", "Over", threshold, float(h + a > threshold)),
        ):
            if key == "moneyline" and h == a:
                continue
            for sample, target in ((samples, results), (pooled, reference)):
                p = outcome_probability(
                    sample, market, selection, line, g["home_team"], g["away_team"]
                )
                decisive = p["win"] + p["loss"]
                if not decisive:
                    continue
                target[key].append((p["win"] / decisive, outcome))
    paired_model, paired_market = [], []
    for row in diagnostic:
        g = row["game"]
        market = market_probability(g)
        if market is None or g["home_score"] == g["away_score"]:
            continue
        p = outcome_probability(
            score_samples(artifact, row["features"]),
            "h2h",
            g["home_team"],
            None,
            g["home_team"],
            g["away_team"],
        )
        outcome = float(g["home_score"] > g["away_score"])
        paired_model.append((p["win"] / (1 - p["push"]), outcome))
        paired_market.append((market, outcome))
    report = {
        "model_version": version,
        "status": "SHADOW_ONLY",
        "approved_for_betting": False,
        "source_checksum": checksum,
        "history_games": len(all_games),
        "split_counts": {
            "fit_through_2023": len(fitting),
            "residual_calibration_2024": len(calibration),
            "diagnostic_2025": len(diagnostic),
        },
        "diagnostic_thresholds": {"home_spread": spread, "total": threshold},
        "model": {k: bucket_metrics(v) for k, v in results.items()},
        "pooled_calibration_score_reference": {k: bucket_metrics(v) for k, v in reference.items()},
        "paired_market_diagnostic": {
            "model": bucket_metrics(paired_model),
            "market": bucket_metrics(paired_market),
            "timestamp_verified_prices": 0,
        },
        "limitations": artifact["limitations"],
    }
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "artifact.json").write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sport", choices=("nfl", "mlb"))
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    report = train(args.source, args.output, args.sport)
    print(json.dumps({k: report[k] for k in ("model_version", "split_counts", "model")}))

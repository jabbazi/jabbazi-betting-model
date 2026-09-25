"""Expanding chronological champions/challengers with separate residual/calibration windows.

Retrospective availability uses the documented two-day score receipt proxy.
No ROI/CLV claims without timestamped historical offered prices.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from datetime import UTC, datetime
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.multioutput import MultiOutputRegressor
from jabazi.models.form_features import POLICIES
from jabazi.models.score_distribution import FEATURES, available_at, score_samples, state_from_games
from jabazi.models.team_elo import SPORTS, timestamp, market_probability
from jabazi.research.train_scores import training_rows
from jabazi.research.calibration_report import fit as fit_cal, transform, report


def predictions(samples, sport):
    s = np.asarray(samples)
    h, a = s[:, 0], s[:, 1]
    spread = -1.5 if sport == "mlb" else -3.5
    total = 8.5 if sport == "mlb" else 44.5
    team = 4.5 if sport == "mlb" else 23.5
    decisive = h != a
    return {
        "moneyline": float((h[decisive] > a[decisive]).mean()) if decisive.any() else 0.5,
        "spread": float((h - a + spread > 0).mean()),
        "total": float((h + a > total).mean()),
        "team_total": float((h > team).mean()),
        "alternate_spread": float((h - a + 10.5 > 0).mean()),
        "alternate_total": float((h + a > total + 4).mean()),
    }


def labels(g, sport):
    h, a = g["home_score"], g["away_score"]
    return {
        "moneyline": None if h == a else int(h > a),
        "spread": int(h - a > (1.5 if sport == "mlb" else 3.5)),
        "total": int(h + a > (8.5 if sport == "mlb" else 44.5)),
        "team_total": int(h > (4.5 if sport == "mlb" else 23.5)),
        "alternate_spread": int(h - a + 10.5 > 0),
        "alternate_total": int(h + a > (12.5 if sport == "mlb" else 48.5)),
    }


def run(source, output, sport):
    raw = Path(source).read_bytes()
    payload = json.loads(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    raw_rows = training_rows(payload, sport)
    weighted_rows = training_rows(payload, sport, POLICIES[sport])
    by_id = {r["game"]["game_id"]: r for r in raw_rows}
    rows = [r for r in weighted_rows if r["game"]["game_id"] in by_id]
    test = [r for r in rows if r["game"]["season"] == 2025]
    if len(test) < 100:
        raise ValueError("Insufficient real 2025 evaluation games")
    # Group by calendar month; all fit labels must be available BEFORE first forecast.
    periods = sorted({r["game"]["starts_at"][:7] for r in test})
    old_path = Path(__file__).parents[1] / "models/artifacts" / f"{sport}_scores.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else None
    names = ["recency_ridge", "recency_boosted"] + (["champion"] if old else [])
    if sport == "mlb":
        names += ["poisson", "negative_binomial"]
    outputs = {name: [] for name in names}
    folds = []
    final_artifact = None
    for period in periods:
        evaluation = [r for r in test if r["game"]["starts_at"].startswith(period)]
        cutoff = min(timestamp(r["game"]["starts_at"]) for r in evaluation)
        prior = [r for r in rows if available_at(r["game"]) < cutoff]
        # Block boundaries use dates, preventing games on one date straddling windows.
        window = 300 if sport == "mlb" else 160
        split1 = prior[-2 * window]["game"]["starts_at"][:10]
        split2 = prior[-window]["game"]["starts_at"][:10]
        train = [
            r
            for r in prior
            if r["game"]["starts_at"][:10] < split1
            and available_at(r["game"]) < timestamp(split1 + "T00:00:00Z")
        ]
        residual = [
            r
            for r in prior
            if split1 <= r["game"]["starts_at"][:10] < split2
            and available_at(r["game"]) < timestamp(split2 + "T00:00:00Z")
        ]
        cal = [r for r in prior if r["game"]["starts_at"][:10] >= split2]
        if min(len(train), len(residual), len(cal)) < 100:
            raise ValueError(
                f"Insufficient disjoint fold {period}: {len(train), len(residual), len(cal)}"
            )
        x = np.array([r["features"] for r in train])
        y = np.array([[r["game"]["home_score"], r["game"]["away_score"]] for r in train])
        scaler = StandardScaler().fit(x)
        age = np.array([(cutoff - timestamp(r["game"]["starts_at"])).days for r in train])
        weights = np.exp(-np.log(2) * age / (365 if sport != "cfb" else 240))
        estimators = {
            "recency_ridge": Ridge(alpha=100).fit(scaler.transform(x), y, sample_weight=weights),
            "recency_boosted": MultiOutputRegressor(
                HistGradientBoostingRegressor(
                    max_iter=60, max_leaf_nodes=7, l2_regularization=20, random_state=42
                )
            ).fit(scaler.transform(x), y, sample_weight=weights),
        }
        r_x = scaler.transform([r["features"] for r in residual])
        r_y = np.array([[r["game"]["home_score"], r["game"]["away_score"]] for r in residual])
        residuals = {k: r_y - m.predict(r_x) for k, m in estimators.items()}
        means = {
            k: m.predict(scaler.transform([r["features"] for r in cal + evaluation]))
            for k, m in estimators.items()
        }
        fold = {
            "period": period,
            "prediction_start": cutoff.isoformat(),
            "train_n": len(train),
            "residual_n": len(residual),
            "calibration_n": len(cal),
            "test_n": len(evaluation),
            "train_last_label_available": max(available_at(r["game"]) for r in train).isoformat(),
            "residual_start": split1,
            "calibration_start": split2,
            "calibration_last_label_available": max(
                available_at(r["game"]) for r in cal
            ).isoformat(),
        }
        folds.append(fold)
        for name in names:
            if name == "champion":
                for r in evaluation:
                    p = predictions(
                        score_samples(old, by_id[r["game"]["game_id"]]["features"]), sport
                    )
                    outputs[name].append(
                        dict(
                            game=r["game"],
                            raw=p,
                            calibrated={},
                            features=by_id[r["game"]["game_id"]]["features"],
                            fold=period,
                        )
                    )
                continue
            p_all = []
            for i, r in enumerate(cal + evaluation):
                if name in ("poisson", "negative_binomial"):
                    # Shared paired team draws; independence here is an explicit challenger
                    # assumption, not an SGP assumption or fitted correlation claim.
                    mu = np.maximum(0.01, means["recency_ridge"][i])
                    rng = np.random.default_rng(
                        int(
                            hashlib.sha256((str(r["game"]["game_id"]) + name).encode()).hexdigest()[
                                :8
                            ],
                            16,
                        )
                    )
                    if name == "poisson":
                        s = rng.poisson(mu, size=(10000, 2))
                    else:
                        variance = np.var(residuals["recency_ridge"], axis=0)
                        dispersion = np.maximum(0.01, mu * mu / np.maximum(0.01, variance - mu))
                        s = rng.negative_binomial(
                            dispersion, dispersion / (dispersion + mu), size=(10000, 2)
                        )
                else:
                    s = np.maximum(0, np.floor(means[name][i] + residuals[name] + 0.5))
                p_all.append(predictions(s, sport))
            calibrators = {}
            for market in p_all[0]:
                idx = [i for i, r in enumerate(cal) if labels(r["game"], sport)[market] is not None]
                pp = [p_all[i][market] for i in idx]
                yy = [labels(cal[i]["game"], sport)[market] for i in idx]
                for method in ("platt", "isotonic", "beta"):
                    try:
                        calibrators[(market, method)] = fit_cal(pp, yy, method)
                    except ValueError:
                        pass
            for i, r in enumerate(evaluation, start=len(cal)):
                pp = p_all[i]
                calibrated = {
                    method: {
                        m: float(transform(c, [pp[m]], method)[0])
                        for (m, met), c in calibrators.items()
                        if met == method
                    }
                    for method in ("platt", "isotonic", "beta")
                }
                outputs[name].append(
                    dict(
                        game=r["game"],
                        raw=pp,
                        calibrated=calibrated,
                        features=r["features"],
                        fold=period,
                    )
                )
        ridge = estimators["recency_ridge"]
        final_artifact = dict(
            schema_version=1,
            sport=SPORTS[sport],
            model_name=f"{sport}_recency_opponent_score_research",
            model_version=f"{sport}-recency-ridge-0.2.0-{checksum[:12]}-{period}",
            status="SHADOW_ONLY",
            approved_for_betting=False,
            features=list(FEATURES),
            feature_schema_version="recency-opponent-form-v2",
            feature_policy=POLICIES[sport],
            mean=scaler.mean_.tolist(),
            scale=scaler.scale_.tolist(),
            coefficients=ridge.coef_.tolist(),
            intercepts=ridge.intercept_.tolist(),
            residual_pairs=residuals["recency_ridge"].tolist(),
            source_checksum=checksum,
            trained_at=datetime.now(UTC).isoformat(),
            training_data_cutoff=fold["train_last_label_available"],
            calibration_version=None,
            state_refreshed_at=datetime.now(UTC).isoformat(),
            window=20 if sport == "mlb" else 8,
            minimum_games=10 if sport == "mlb" else 4,
            team_state=state_from_games(
                payload["games"], now=datetime.now(UTC), window=20 if sport == "mlb" else 8
            ),
            events=[],
            code_commit=subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
            limitations=[
                "SHADOW_ONLY: no frozen prospective validation",
                "Score-based opponent adjustment, not EPA or personnel model",
                "Historical availability is a two-day proxy, not original timestamped receipts",
                "No timestamped offered odds, ROI or CLV evidence",
                "2025 diagnostic already viewed for NFL/MLB; no untouched model-selection claim",
                "Calibrator candidates evaluated only offline; applying separate transforms can break joint coherence",
                "Roster, QB, starter, injury, weather and CFB returning-production inputs unavailable",
            ],
        )
    results = {}
    for name, forecast in outputs.items():
        results[name] = {}
        for market in forecast[0]["raw"]:
            eligible = [r for r in forecast if labels(r["game"], sport)[market] is not None]
            y = [labels(r["game"], sport)[market] for r in eligible]
            result = {"raw": report([r["raw"][market] for r in eligible], y)}
            for method in ("platt", "isotonic", "beta"):
                available = [r for r in eligible if market in r["calibrated"].get(method, {})]
                result[method] = report(
                    [r["calibrated"][method][market] for r in available],
                    [labels(r["game"], sport)[market] for r in available],
                )
            if market == "moneyline":
                paired = [r for r in eligible if market_probability(r["game"]) is not None]
                result["market_reference"] = report(
                    [market_probability(r["game"]) for r in paired],
                    [labels(r["game"], sport)[market] for r in paired],
                )
                result["paired_model"] = report(
                    [r["raw"][market] for r in paired],
                    [labels(r["game"], sport)[market] for r in paired],
                )
            results[name][market] = result
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "sport": sport,
        "dataset_sha256": checksum,
        "model_version": final_artifact["model_version"],
        "folds": folds,
        "status": "SHADOW_ONLY",
        "prospective_predictions": 0,
        "promotion": "NONE",
        "results": results,
        "roi": None,
        "clv": None,
        "timestamp_verified_historical_prices": 0,
        "evaluation_scope": "Monthly expanding origin on 2025; fixed synthetic thresholds diagnose distributions, not actual offered betting opportunities. All hyperparameters fixed before this run. No architecture promoted.",
        "limitations": final_artifact["limitations"],
    }
    (out / "report.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    (out / "challenger-artifact.json").write_text(
        json.dumps(final_artifact, allow_nan=False) + "\n"
    )
    # Freeze input/prediction rows for reproducibility (retrospective, clearly labeled).
    (out / "predictions.json").write_text(json.dumps(outputs, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "sport": sport,
                "folds": len(folds),
                "metrics": {
                    n: {m: round(v["raw"]["brier"], 6) for m, v in markets.items()}
                    for n, markets in results.items()
                },
            }
        )
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("sport", choices=SPORTS)
    p.add_argument("source")
    p.add_argument("output")
    a = p.parse_args()
    run(a.source, a.output, a.sport)

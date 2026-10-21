"""Reproducible NHL season-separated experiment; no synthetic data or promotion."""

import argparse
import gzip
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, PoissonRegressor

from jabazi.models.nhl_goals import (
    SETTLEMENT,
    NHLGoalsModel,
    feature_pair,
    probability,
    rates,
    score_grid,
    team_state,
)
from jabazi.models.team_elo import timestamp
from jabazi.providers.nhl import NAMES, SCHEMA, SPORT, rows

MARKET_DIAGNOSTICS = [("h2h", None), ("spreads", -1.5), ("totals", 6.5), ("team_totals", 3.5)]


def design(games, league):
    state, output, pending = {}, [], []
    for game in games:
        start = timestamp(game["starts_at"])
        ready = [g for g in pending if timestamp(g["available_at"]) < start]
        pending = [g for g in pending if timestamp(g["available_at"]) >= start]
        for old in ready:
            for side, other in (("home", "away"), ("away", "home")):
                state.setdefault(old[f"{side}_team"], []).append(
                    [
                        old[f"regulation_{side}"],
                        old[f"regulation_{other}"],
                        old["starts_at"],
                        old["available_at"],
                        old["game_id"],
                    ]
                )
        pair = feature_pair(state, game, start, league)
        if pair:
            output.append({"game": game, "vectors": pair})
        pending.append(game)
    return output


def fit(records, alpha, league):
    x = [v for row in records for v in row["vectors"]]
    y = [row["game"][f"regulation_{side}"] for row in records for side in ("home", "away")]
    model = PoissonRegressor(alpha=alpha, max_iter=1000, tol=1e-9).fit(x, y)
    ties = [r["game"] for r in records if r["game"]["last_period_type"] != "REG"]
    return {
        "coefficients": model.coef_.tolist(),
        "intercept": float(model.intercept_),
        "league_rate": league,
        "goal_rate_calibration": 1.0,
        "overtime_home_probability": (1 + sum(g["home_score"] > g["away_score"] for g in ties))
        / (2 + len(ties)),
        "overtime_training_games": len(ties),
        "alpha": alpha,
    }


def goal_loss(model, records):
    losses = []
    for row in records:
        for side, rate in zip(("home", "away"), rates(model, row["vectors"])):
            y = row["game"][f"regulation_{side}"]
            losses.append(rate - y * math.log(rate) + math.lgamma(y + 1))
    return float(np.mean(losses))


def calibrate(model, records):
    pred = sum(sum(rates(model, r["vectors"], calibrated=False)) for r in records)
    actual = sum(r["game"]["regulation_home"] + r["game"]["regulation_away"] for r in records)
    return model | {"goal_rate_calibration": actual / pred}


def predict(model, records):
    results = []
    for row in records:
        g = row["game"]
        grid = score_grid(*rates(model, row["vectors"]), model["overtime_home_probability"])
        for market, line in MARKET_DIAGNOSTICS:
            sel = g["home_team"] if market in {"h2h", "spreads"} else "Over"
            par = g["home_team"] if market == "team_totals" else None
            p = probability(grid, market, sel, line, g["home_team"], g["away_team"], par)["win"]
            actual = probability(
                {(g["home_score"], g["away_score"]): 1.0},
                market,
                sel,
                line,
                g["home_team"],
                g["away_team"],
                par,
            )["win"]
            results.append(
                {
                    "game_id": g["game_id"],
                    "starts_at": g["starts_at"],
                    "season": g["season"],
                    "market": market,
                    "line": line,
                    "probability": p,
                    "outcome": actual,
                    "feature_snapshot": row["vectors"],
                }
            )
    return results


def summary(predictions):
    result = {}
    for market, _ in MARKET_DIAGNOSTICS:
        rows = [r for r in predictions if r["market"] == market]
        p = np.array([r["probability"] for r in rows])
        y = np.array([r["outcome"] for r in rows])
        logits = np.log(np.clip(p, 1e-9, 1 - 1e-9) / np.clip(1 - p, 1e-9, 1))
        reg = LogisticRegression(C=1e6).fit(logits.reshape(-1, 1), y)
        table = []
        for low, high in zip(
            [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95],
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.000001],
        ):
            mask = (p >= low) & (p < high)
            n = int(mask.sum())
            if not n:
                continue
            obs = float(y[mask].mean())
            z = 1.96
            denom = 1 + z * z / n
            center = (obs + z * z / (2 * n)) / denom
            half = z * math.sqrt(obs * (1 - obs) / n + z * z / (4 * n * n)) / denom
            table.append(
                {
                    "bucket": f"{100 * low:g}-{min(100, 100 * high):g}",
                    "n": n,
                    "mean_probability": float(p[mask].mean()),
                    "observed_hit_rate": obs,
                    "wilson_95": [center - half, center + half],
                }
            )
        result[market] = {
            "independent_games": len(rows),
            "predictions": len(rows),
            "brier": float(np.mean((p - y) ** 2)),
            "log_loss": float(
                -np.mean(
                    y * np.log(np.clip(p, 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-9, 1))
                )
            ),
            "calibration_intercept": float(reg.intercept_[0]),
            "calibration_slope": float(reg.coef_[0, 0]),
            "ece": sum(r["n"] * abs(r["mean_probability"] - r["observed_hit_rate"]) for r in table)
            / len(rows),
            "reliability": table,
            "market_baseline": None,
            "clv": None,
            "roi": None,
        }
    return result


def run(directory, output, artifact_path):
    directory, output = Path(directory), Path(output)
    receipts = json.loads((directory / "receipts.json").read_text())
    sources = []
    for receipt in receipts:
        if "error_type" in receipt:
            raise ValueError("Incomplete NHL capture")
        raw = (directory / receipt["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            raise ValueError("NHL source checksum mismatch")
        sources.append(json.loads(raw))
    all_rows = rows(sources)
    games = [g for g in all_rows if g["completed"]]
    # All four published 82-game regular seasons must be complete, not cherry-picked.
    counts = {
        s: sum(g["season"] == s for g in games) for s in (20222023, 20232024, 20242025, 20252026)
    }
    if any(n != 1312 for n in counts.values()):
        raise ValueError(f"Incomplete historical NHL seasons: {counts}")
    train_games = [g for g in games if g["season"] <= 20232024]
    league = sum(g["regulation_home"] + g["regulation_away"] for g in train_games) / (
        2 * len(train_games)
    )
    # Initial selection uses a prior calculated on 2022–23 only.
    first = [g for g in games if g["season"] == 20222023]
    first_league = sum(g["regulation_home"] + g["regulation_away"] for g in first) / (
        2 * len(first)
    )
    initial = design(games, first_league)
    selection = []
    for alpha in (0.01, 0.1, 1.0):
        m = fit([r for r in initial if r["game"]["season"] == 20222023], alpha, first_league)
        selection.append(
            {
                "alpha": alpha,
                "selection_goal_log_loss": goal_loss(
                    m, [r for r in initial if r["game"]["season"] == 20232024]
                ),
            }
        )
    chosen = min(selection, key=lambda r: r["selection_goal_log_loss"])["alpha"]
    data = design(games, league)
    train = [r for r in data if r["game"]["season"] <= 20232024]
    calibration = [r for r in data if r["game"]["season"] == 20242025]
    test = [r for r in data if r["game"]["season"] == 20252026]
    model = fit(train, chosen, league)
    h = np.mean([r["game"]["regulation_home"] for r in train])
    a = np.mean([r["game"]["regulation_away"] for r in train])
    baseline = model | {
        "coefficients": [0, 0, float(math.log(h / a)), 0, 0],
        "intercept": float(math.log(a)),
    }
    calibrated = calibrate(model, calibration)
    baseline = calibrate(baseline, calibration)
    predictions = {
        "league_baseline": predict(baseline, test),
        "raw_form_model": predict(model, test),
        "calibrated_form_model": predict(calibrated, test),
    }
    report = {
        "historical_games": counts,
        "fit_games": len(train),
        "calibration_games": len(calibration),
        "test_games": len(test),
        "selection": selection,
        "selected_alpha": chosen,
        "calibration_goal_factor": calibrated["goal_rate_calibration"],
        "test": {k: summary(v) for k, v in predictions.items()},
        "paired_brier_difference": {},
    }
    rng = np.random.default_rng(20260928)
    for market, _ in MARKET_DIAGNOSTICS:
        arows = [r for r in predictions["calibrated_form_model"] if r["market"] == market]
        brows = [r for r in predictions["league_baseline"] if r["market"] == market]
        delta = np.array(
            [
                (a["probability"] - a["outcome"]) ** 2 - (b["probability"] - b["outcome"]) ** 2
                for a, b in zip(arows, brows, strict=True)
            ]
        )
        boot = np.mean(delta[rng.integers(0, len(delta), size=(2000, len(delta)))], axis=1)
        report["paired_brier_difference"][market] = {
            "model_minus_baseline": float(delta.mean()),
            "game_bootstrap_95": np.quantile(boot, [0.025, 0.975]).tolist(),
        }
    now = datetime.now(UTC)
    checksum = hashlib.sha256(
        json.dumps(sorted((r["file"], r["sha256"]) for r in receipts)).encode()
    ).hexdigest()
    version = (
        "nhl-poisson-form-0.1.0-"
        + hashlib.sha256(json.dumps(calibrated, sort_keys=True).encode()).hexdigest()[:12]
    )
    # Live opening schedule is captured separately, never used in fitting.
    opening = json.loads((directory / "opening.json").read_text())
    events = rows([{"games": [g for d in opening["gameWeek"] for g in d["games"]]}])
    events = [
        e
        for e in events
        if not e["completed"]
        and e["scheduled"]
        and now < timestamp(e["starts_at"]) <= now + timedelta(days=10)
    ]
    # Wide numerical feature domain is a guard, not a learned confidence bound.
    ranges = [[math.log(0.5), math.log(7)], [math.log(0.5), math.log(7)], [0, 1], [0, 7], [0, 7]]
    artifact = calibrated | {
        "schema_version": 1,
        "sport": SPORT,
        "model_name": "NHL regulation Poisson form + empirical OT/SO",
        "model_version": version,
        "feature_schema_version": SCHEMA,
        "settlement": SETTLEMENT,
        "trained_at": now.isoformat(),
        "training_data_cutoff": "2024-07-01T00:00:00+00:00",
        "calibration_data_cutoff": "2025-07-01T00:00:00+00:00",
        "calibration_version": "nhl-shared-goal-rate-2024-25-v1",
        "source_checksum": checksum,
        "state_source_checksum": checksum,
        "state_refreshed_at": now.isoformat(),
        "team_state": team_state(games, now),
        "events": events,
        "active_season": 20262027,
        "clubs": sorted(set(NAMES) - {"ARI"}),
        "feature_ranges": ranges,
        "training_feature_mean": np.mean([v for r in train for v in r["vectors"]], axis=0).tolist(),
        "training_feature_std": np.std([v for r in train for v in r["vectors"]], axis=0).tolist(),
        "validation": {"test_sample_count": len(test), "prospective_sample_count": 0},
        "stage": "SHADOW_ONLY",
        "approved_for_betting": False,
        "limitations": [
            "No confirmed goalie, roster or injury inputs",
            "Independent regulation Poisson assumption; empty-net tactics not modeled",
            "Pooled overtime/shootout home-win rate; no goalie-specific OT skill",
            "No timestamped historical odds, CLV or market-relative evidence",
            "Historical availability is start plus 48 hours, not archived publication timestamps",
            "No NHL player props, regulation-only, first-period or playoff coverage",
            "Book-specific settlement unverified; whole-line push markets withheld from binary scanner EV",
            "Prospective sample is zero; no betting approval",
        ],
    }
    NHLGoalsModel(artifact)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (output / "source_receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    with gzip.GzipFile(filename=str(output / "test_predictions.json.gz"), mode="wb", mtime=0) as f:
        f.write(json.dumps(predictions, separators=(",", ":"), allow_nan=False).encode())
    Path(artifact_path).write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "version": version,
                "events": len(events),
                "report": {
                    k: {m: {x: v for x, v in s.items() if x != "reliability"} for m, s in d.items()}
                    for k, d in report["test"].items()
                },
                "delta": report["paired_brier_difference"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--artifact", required=True)
    args = p.parse_args()
    run(args.inputs, args.output, args.artifact)

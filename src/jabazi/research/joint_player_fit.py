"""Historical two-market, same-player dependence experiments for NBA/NHL.

Fits empirical residual ranks after marginal training and evaluates a later
untouched season. Fixed thresholds are research benchmarks, not sportsbook
quotes. Reconstructed history is never labeled prospective evidence.
"""
from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite, log
from random import Random

from jabazi.models.player_distribution import raw_probability
from jabazi.models.player_joint import checkerboard_joint
from jabazi.research.prop_data import inspect_prop_dataset, timestamp


SPECS = {
    "basketball_nba": [
        (("player_points", "player_rebounds"), (19.5, 5.5)),
        (("player_points", "player_assists"), (19.5, 4.5)),
        (("player_rebounds", "player_assists"), (5.5, 4.5)),
    ],
    "icehockey_nhl": [
        (("player_goals", "player_shots_on_goal"), (.5, 2.5)),
        (("player_goals", "player_assists"), (.5, .5)),
        (("player_assists", "player_shots_on_goal"), (.5, 2.5)),
    ],
}


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def pit(row, artifact):
    """Deterministic independent jitter inside a discrete count CDF atom."""
    value = row["observed_value"]
    lower = 1 - raw_probability(artifact, row["features"], "over", value - .5)
    upper = 1 - raw_probability(artifact, row["features"], "over", value + .5)
    if not all(isfinite(x) for x in (lower, upper)) or not 0 <= lower <= upper <= 1:
        raise ValueError("Invalid marginal CDF")
    key = [row["event_id"], row["player_id"], artifact["market"]]
    jitter = int(fingerprint(key)[:13], 16) / 16**13
    return lower + (upper - lower) * jitter


def rank_pairs(values):
    ranks = [[0, 0] for _ in values]
    for axis in (0, 1):
        for rank, index in enumerate(sorted(range(len(values)),
                                            key=lambda i: (values[i][axis], i))):
            ranks[index][axis] = rank
    return ranks


def joint_evaluator(ranks):
    if len(ranks) < 1000:
        return lambda ps: checkerboard_joint(ranks, ps, [True, True])
    import numpy as np
    cells = np.asarray(ranks, dtype=float) + 1
    n = len(cells)

    def evaluate(ps):
        if any(not isfinite(p) or not 0 <= p <= 1 for p in ps):
            raise ValueError("Invalid joint marginal")
        fractions = np.clip(cells - n * (1 - np.asarray(ps)), 0, 1)
        value = float(np.mean(fractions[:, 0] * fractions[:, 1]))
        return min(min(ps), max(0, sum(ps)-1, value))
    return evaluate


def scores(predictions):
    events = defaultdict(list)
    for event, probability, independent, outcome in predictions:
        events[event].append((probability, independent, outcome))
    report = {"independent_events": len(events), "pairs": len(predictions)}
    event_scores = {}
    for label, index in (("joint", 0), ("independence", 1)):
        brier, loss = [], []
        for rows in events.values():
            brier.append(sum((r[index] - r[2]) ** 2 for r in rows) / len(rows))
            loss.append(sum(-r[2] * log(max(1e-12, r[index]))
                            - (1-r[2]) * log(max(1e-12, 1-r[index]))
                            for r in rows) / len(rows))
        report[label] = {"event_weighted_brier": sum(brier) / len(brier),
                         "event_weighted_log_loss": sum(loss) / len(loss)}
        event_scores[label] = (brier, loss)
    # Paired game bootstrap keeps all same-game player tickets together.
    # It does not remove serial dependence from players recurring across games.
    differences = list(zip(*[
        [b-a for a, b in zip(event_scores["joint"][i], event_scores["independence"][i])]
        for i in (0, 1)]))
    rng = Random(0)
    samples = [[], []]
    for _ in range(1000):
        chosen = rng.choices(differences, k=len(differences))
        for axis in (0, 1):
            samples[axis].append(sum(row[axis] for row in chosen) / len(chosen))
    report["paired_game_bootstrap_95pct"] = {
        key: [sorted(values)[24], sorted(values)[974]]
        for key, values in zip(("brier_improvement", "log_loss_improvement"), samples)
    }
    bins = defaultdict(list)
    for event, rows in events.items():
        for probability, _, outcome in rows:
            bins[min(9, int(probability * 10))].append((probability, outcome, 1/len(rows)))
    calibration, ece = [], 0.0
    for index, rows in sorted(bins.items()):
        mass = sum(w for _, _, w in rows)
        mean = sum(p*w for p, _, w in rows) / mass
        rate = sum(y*w for _, y, w in rows) / mass
        ece += mass * abs(mean-rate) / len(events)
        calibration.append({"lower": index/10, "upper": (index+1)/10,
                            "event_weight": mass, "mean_prediction": mean,
                            "observed_rate": rate})
    report["calibration_bins"] = calibration
    report["event_weighted_ece"] = ece
    report["beats_independence_on_both_scores"] = all(
        report["joint"][key] < report["independence"][key]
        for key in ("event_weighted_brier", "event_weighted_log_loss"))
    return report


def fit_joint_research(documents, marginals, *, sport, fit_start, test_start,
                       test_end, minimum_events=200):
    if sport not in SPECS or type(minimum_events) is not int or minimum_events < 2:
        raise ValueError("Unsupported sport or independent-game minimum")
    left, right, end = map(timestamp, (fit_start, test_start, test_end))
    if not left < right < end:
        raise ValueError("Invalid chronological windows")
    markets = sorted({market for pair, _ in SPECS[sport] for market in pair})
    indexed, sources = {}, {}
    event_times = {}
    for market in markets:
        document, marginal = documents[market], marginals[market]
        manifest = document.get("manifest", {})
        if (manifest.get("sport"), manifest.get("market")) != (sport, market):
            raise ValueError("Dataset sport/market mismatch")
        inspect_prop_dataset(document, train_before=fit_start,
                             test_before=test_start, minimum_per_split=1)
        if (marginal.get("sport"), marginal.get("market")) != (sport, market):
            raise ValueError("Marginal sport/market mismatch")
        if marginal.get("family") != "count_nb" or not marginal.get("model_version"):
            raise ValueError("Versioned count marginal required")
        if timestamp(marginal["training_cutoff"]) >= left:
            raise ValueError("Marginal training overlaps dependence fit")
        # Use raw distributions consistently: fitted threshold calibrations are
        # not transferable to residual ranks or arbitrary benchmark lines.
        if marginal.get("calibration") is not None:
            raise ValueError("Calibrated marginal requires a separate locked protocol")
        sources[market] = {"document_sha256": fingerprint(document),
                           "marginal_sha256": fingerprint(marginal),
                           "provider": manifest["provider"],
                           "source_checksum": manifest["source_checksum"],
                           "marginal_version": marginal["model_version"]}
        indexed[market] = {}
        for row in document["rows"]:
            start = timestamp(row["starts_at"])
            old = event_times.setdefault(row["event_id"], start)
            if old != start:
                raise ValueError("Cross-market event identity mismatch")
            if row.get("result_status") != "final":
                continue
            indexed[market][(row["event_id"], row["player_id"])] = row

    buckets = []
    for pair, lines in SPECS[sport]:
        keys = sorted(set(indexed[pair[0]]) & set(indexed[pair[1]]))
        fitting, held = [], []
        excluded_boundary = 0
        for key in keys:
            rows = [indexed[market][key] for market in pair]
            decisions = [timestamp(r["prediction_at"]) for r in rows]
            if decisions[0] != decisions[1]:
                raise ValueError("Aligned forecasts must share a decision time")
            decision = decisions[0]
            results = [timestamp(r["result_available_at"]) for r in rows]
            if left <= decision < right:
                if max(results) >= right:
                    excluded_boundary += 1
                    continue
                fitting.append(rows)
            elif right <= decision < end:
                if max(results) >= end:
                    excluded_boundary += 1
                    continue
                held.append(rows)
        fit_events = {rows[0]["event_id"] for rows in fitting}
        test_events = {rows[0]["event_id"] for rows in held}
        if fit_events & test_events:
            raise ValueError("Event overlap between fit and test")
        bucket = {"relationship": "same_player", "markets": list(pair),
                  "benchmark_lines": list(lines), "training_pairs": len(fitting),
                  "training_unique_games": len(fit_events),
                  "test_unique_games": len(test_events),
                  "excluded_split_boundary_pairs": excluded_boundary,
                  "marginal_versions": [marginals[m]["model_version"] for m in pair],
                  "status": "INSUFFICIENT_INDEPENDENT_EVENTS"}
        if min(len(fit_events), len(test_events)) >= minimum_events:
            ranks = rank_pairs([[pit(row, marginals[m]) for row, m in zip(rows, pair)]
                                for rows in fitting])
            evaluate = joint_evaluator(ranks)
            predictions = []
            for rows in held:
                ps = [raw_probability(marginals[m], row["features"], "over", line)
                      for m, row, line in zip(pair, rows, lines)]
                outcome = int(all(row["observed_value"] > line
                                  for row, line in zip(rows, lines)))
                predictions.append((rows[0]["event_id"],
                                    evaluate(ps),
                                    ps[0] * ps[1], outcome))
            bucket.update(ranks=ranks, holdout=scores(predictions),
                          status="HISTORICAL_RESEARCH_FIT")
        buckets.append(bucket)
    artifact = {
        "schema_version": 1, "artifact_type": "same_player_joint_research",
        "sport": sport, "stage": "SHADOW_ONLY", "approved_for_betting": False,
        "prospective_sample_count": 0, "market_baseline_verified": False,
        "fit_start": left.isoformat(), "test_start": right.isoformat(),
        "test_end": end.isoformat(), "sources": sources, "buckets": buckets,
        "limitations": ["Reconstructed history, not frozen prospective forecasts",
                        "Fixed benchmark thresholds, not executable sportsbook quotes",
                        "Same-player two-market counts only; no cross-player or goalie pairs",
                        "No participation/void model or live boost routing",
                        "Historical residual dependence may not transfer to current players"],
    }
    fitted_identity = {
        "sport": sport, "fit_start": left.isoformat(), "fit_end": right.isoformat(),
        "marginals": {m: fingerprint(marginals[m]) for m in markets},
        "buckets": [{k: b.get(k) for k in ("markets", "ranks", "benchmark_lines")}
                    for b in buckets],
    }
    artifact["model_version"] = sport + "-joint-research-" + fingerprint(fitted_identity)[:12]
    return artifact

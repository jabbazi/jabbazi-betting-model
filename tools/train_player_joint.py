"""Fit NFL two-prop residual-rank copulas on 2024; evaluate untouched 2025.

Reuses the pinned capture manifest and existing pre-2024 marginal models. Historical
reconstruction is not prospective evidence and never confers betting approval.
"""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import correlation

from jabazi.models.player_distribution import raw_probability, calibrated_probability
from jabazi.models.player_joint import checkerboard_joint, SPORT
from tools.capture_nfl_player_props import parse_asset
from tools.capture_nfl_context import schedule_rows

SPECS = [
    ("same_player", ("player_receptions", "player_reception_yds"), (r, r), (3.5, 49.5))
    for r in ("WR", "TE", "RB")
] + [
    ("same_player", ("player_rush_attempts", "player_rush_yds"), ("RB", "RB"), (12.5, 49.5)),
    (
        "same_player",
        ("player_pass_attempts", "player_pass_completions"),
        ("QB", "QB"),
        (30.5, 20.5),
    ),
    ("same_player", ("player_pass_yds", "player_pass_tds"), ("QB", "QB"), (225.5, 1.5)),
    ("same_team", ("player_pass_yds", "player_reception_yds"), ("QB", "WR"), (225.5, 49.5)),
    ("same_team", ("player_pass_yds", "player_reception_yds"), ("QB", "TE"), (225.5, 39.5)),
]


def pit(row, artifact):
    y, f = row["observed_value"], row["features"]
    if artifact["family"] == "count_nb":
        lo = 1 - raw_probability(artifact, f, "over", y - 0.5)
        hi = 1 - raw_probability(artifact, f, "over", y + 0.5)
    elif artifact["family"] == "hurdle_lognormal" and y == 0:
        lo, hi = 0, 1 - raw_probability(artifact, f, "over", 0)
    else:
        lo = hi = 1 - raw_probability(artifact, f, "over", y)
    # Reproducible independent jitter within a discrete CDF atom, never by result.
    key = [row["event_id"], row["player_id"], artifact["market"]]
    u = int(sha256(json.dumps(key).encode()).hexdigest()[:13], 16) / 16**13
    return lo + (hi - lo) * u


def rank_pairs(values):
    ranks = [[0, 0] for _ in values]
    for axis in (0, 1):
        for rank, i in enumerate(sorted(range(len(values)), key=lambda i: (values[i][axis], i))):
            ranks[i][axis] = rank
    return ranks


def train(capture, output):
    receipts = json.loads((capture / "receipts.json").read_text())
    schedule = schedule_rows((capture / "raw/games.csv").read_text(), set(range(2021, 2026)))
    identities = {}
    for path in sorted((capture / "raw").glob("*.gz")):
        for r in parse_asset(path, schedule):
            key = (r["event_id"], r["player_id"])
            if key in identities:
                raise ValueError("Duplicate player game")
            identities[key] = r
    markets = {m for s in SPECS for m in s[1]}
    artifacts = {
        m: json.loads((Path("models/player_props") / SPORT / (m + ".json")).read_text())
        for m in markets
    }
    if any(a["training_cutoff"] >= "2024-01-01" for a in artifacts.values()):
        raise ValueError("Marginal training overlaps correlation/holdout window")
    documents = {m: json.loads((capture / (m + ".json")).read_text())["rows"] for m in markets}
    grouped = {}
    for m, rows in documents.items():
        grouped[m] = defaultdict(list)
        for r in rows:
            ident = identities[(r["event_id"], r["player_id"])]
            if ident["season"] not in (2024, 2025):
                continue
            if (
                r["features_available_at"] >= r["prediction_at"]
                or r["prediction_at"] >= r["starts_at"]
            ):
                raise ValueError("Noncausal player features")
            grouped[m][(r["event_id"], ident["team"], ident["position"])].append(r)
    buckets = []
    for relation, markets, roles, lines in SPECS:
        pairs = []
        for (gid, team, role), rows in grouped[markets[0]].items():
            if role != roles[0]:
                continue
            # Include all eligible players; count distinct games separately because
            # teammates and repeated player appearances are not independent samples.
            seconds = grouped[markets[1]].get((gid, team, roles[1]), [])
            for first in rows:
                for second in seconds:
                    same = first["player_id"] == second["player_id"]
                    if same == (relation == "same_player"):
                        pairs.append((first, second))
        fitting = [
            p for p in pairs if identities[(p[0]["event_id"], p[0]["player_id"])]["season"] == 2024
        ]
        held = [
            p for p in pairs if identities[(p[0]["event_id"], p[0]["player_id"])]["season"] == 2025
        ]
        if len(fitting) < 100 or len(held) < 100:
            continue
        ranks = rank_pairs(
            [[pit(r, artifacts[m]) for r, m in zip(pair, markets)] for pair in fitting]
        )
        predictions = []
        for pair in held:
            ps = [
                calibrated_probability(artifacts[m], r["features"], "over", line)
                for r, m, line in zip(pair, markets, lines)
            ]
            y = int(all(r["observed_value"] > line for r, line in zip(pair, lines)))
            predictions.append((checkerboard_joint(ranks, ps, [True, True]), ps[0] * ps[1], y))
        brier = sum((p - y) ** 2 for p, _, y in predictions) / len(predictions)
        independent = sum((p - y) ** 2 for _, p, y in predictions) / len(predictions)
        buckets.append(
            dict(
                relationship=relation,
                markets=list(markets),
                positions=list(roles),
                marginal_versions=[artifacts[m]["model_version"] for m in markets],
                training_unique_games=len({p[0]["event_id"] for p in fitting}),
                ranks=ranks,
                rank_correlation=correlation(*zip(*ranks)),
                research_admitted=brier < independent,
                holdout=dict(
                    season=2025,
                    pairs=len(held),
                    unique_games=len({p[0]["event_id"] for p in held}),
                    benchmark_lines=lines,
                    joint_brier=brier,
                    independence_brier=independent,
                    mean_joint_probability=sum(p for p, _, _ in predictions) / len(predictions),
                    observed_joint_rate=sum(y for _, _, y in predictions) / len(predictions),
                    beats_independence=brier < independent,
                ),
            )
        )
    artifact = dict(
        schema_version=1,
        sport=SPORT,
        model_version="nfl-player-joint-ranks-0.1.0",
        source_checksum=sha256(
            json.dumps(sorted(r["sha256"] for r in receipts)).encode()
        ).hexdigest(),
        fit_season=2024,
        holdout_season=2025,
        approved_for_betting=False,
        stage="SHADOW_ONLY",
        prospective_sample_count=0,
        buckets=buckets,
        limitations=[
            "Historical reconstructed features; not prospective validation",
            "Benchmark lines are fixed research thresholds, not historical sportsbook quotes",
            "Repeated players and two teams per game are not independent observations",
            "Pooled role dependence assumes transfer to current players",
            "Two prop legs only; no fitted player/team or 3–4 player joint distribution",
        ],
    )
    output.write_text(json.dumps(artifact, separators=(",", ":")) + "\n")
    report = {k: v for k, v in artifact.items() if k != "buckets"}
    report["buckets"] = [{k: v for k, v in b.items() if k != "ranks"} for b in buckets]
    report["receipts"] = receipts
    Path("docs/experiments/nfl-player-joint/report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report["buckets"], indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--capture", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    train(args.capture, args.output)

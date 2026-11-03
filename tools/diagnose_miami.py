"""Reproduce the 2026-09-25 scan from the preserved fitted artifact, without live odds."""

import hashlib
import json
from pathlib import Path
from jabazi.models.score_distribution import FEATURES, features, score_samples, outcome_probability
from jabazi.models.game_distribution import GameDistribution
from jabazi.models.team_elo import timestamp


def diagnose():
    path = Path(__file__).resolve().parents[1] / "src/jabazi/models/artifacts/nfl_scores.json"
    raw = path.read_bytes()
    a = json.loads(raw)
    home, away = "Miami Dolphins", "Kansas City Chiefs"
    start = timestamp("2026-09-27T17:00:00Z")
    v = features(a["team_state"], home, away, start, False, 4)
    samples = score_samples(a, v)
    d = GameDistribution(tuple(samples))
    d.validate_ladders(home, away)
    ml = outcome_probability(samples, "h2h", home, None, home, away)
    rows = {
        str(line): outcome_probability(samples, "spreads", home, line, home, away)["win"]
        for line in (2.5, 7.5, 10.5, 11.5)
    }
    expected = {"2.5": 0.5894736842105263, "7.5": 0.743859649122807, "10.5": 0.8140350877192982}
    assert all(abs(rows[k] - v) < 1e-14 for k, v in expected.items())
    assert abs(ml["win"] / (1 - ml["push"]) - 0.49814126394052044) < 1e-14
    scaled = [(x - m) / s for x, m, s in zip(v, a["mean"], a["scale"], strict=True)]
    checks = {
        "team_ids": "KC/MIA names match nflverse adapter; provider mapping absent from saved tool output",
        "home_away": "Miami home; Kansas City away, matching schedule and quote",
        "event_id": "provider 0339a0e41bcee12820eb3e64bb5fadb4; schedule 2026_03_KC_MIA",
        "season_week": "2026 week 3 from schedule ID; explicit metadata not enforced by old model",
        "date_time": start.isoformat(),
        "roster_version": "UNAVAILABLE: no roster feature",
        "QB_assignment": "UNAVAILABLE: no QB feature",
        "injuries": "UNAVAILABLE: no injury feature",
        "feature_orientation": "home scoring, away scoring, home conceding, away conceding, home-minus-away rest, home field",
        "favorite_sign": "No favorite flag; home margin = home points minus away points",
        "spread_sign": "Miami +10.5 wins when Miami margin + 10.5 > 0",
        "alternate_translation": "Same score samples and same signed handicap as main spread",
        "market_pairing": "Miami +10.5 / Kansas City -10.5 complementary; main market sums to one",
        "outcome_pairing": "Spread wins 232/285; opposite wins 53/285",
        "no_vig": "Main spread consensus .494764397905759 + .505235602094241 = 1",
        "feature_freshness": "Cloud refreshed 2026-09-24T23:21:12Z; bundled Sept23 state reproduces exact output. Per-scan cloud feature snapshot not accessible through read-only tools.",
        "scaling": dict(zip(FEATURES, scaled)),
        "imputation": "None; insufficient history returns None",
        "preprocessing_parity": "Training and inference share features() and score_samples()",
        "residual_variance": d.summary(),
        "calibration": "285 paired 2024 residuals; NOT independently fitted probability calibration",
        "double_transformation": "No probability transform; moneyline explicitly conditions on no tie",
        "stale_strength": "6/8 equally weighted team games from 2025, 2/8 from 2026; no season decay",
        "duplicate_events": "Inference requires exactly one schedule match; provider cross-ID duplicates not checked in old scanner",
        "leakage": "Fitted through 2023; residual year 2024. Availability uses two-day result proxy, not captured historical receipt; no decision-time backtest claim.",
        "suspicious_features": "Finite score means but structurally inadequate personnel/recency coverage; 5.61% simulated ties is a distribution defect requiring better football settlement modeling",
    }
    return {
        "scan_id": "8f4d0c7e-5c5c-4d7b-a0ac-2e55dc19d2c1",
        "model_version": a["model_version"],
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "features": dict(zip(FEATURES, v)),
        "team_history": {t: a["team_state"][t] for t in (home, away)},
        "score_distribution": d.summary(),
        "spread_probabilities": rows,
        "moneyline": ml,
        "conditional_moneyline": ml["win"] / (1 - ml["push"]),
        "checks": checks,
        "conclusion": "Exact arithmetic reproduction. No evidence of Miami spread sign error. Near-even score forecast derives from weak, stale, equally weighted form features without personnel inputs; no validated probability calibration. Extreme market disagreement quarantined, not capped.",
        "status": "MODEL_QUARANTINE",
        "root_cause_confirmed": "Inadequate feature/recency model and missing disagreement admission gate",
        "unverified": "Full frozen production feature snapshot and real personnel state; reproduction is from committed artifact, not a claimed database export",
    }


if __name__ == "__main__":
    print(json.dumps(diagnose(), indent=2, allow_nan=False))

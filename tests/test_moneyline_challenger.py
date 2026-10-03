"""Synthetic data tests for chronology, ablation selection and saved inference."""

import json
import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jabazi.research.moneyline_challenger import (
    checksum, feature_rows, paired_comparison, partitions, train,
)


def history(sport="nfl"):
    return {
        "sport": "americanfootball_nfl" if sport == "nfl" else "baseball_mlb",
        "provider": "SYNTHETIC_TEST_ONLY",
        "games": [{
            "game_id": f"{year}-{i}", "season": year,
            "starts_at": (datetime(year, 3, 1, 18, tzinfo=UTC) + timedelta(days=i)).isoformat(),
            "home_team": "H" if i % 2 else "A", "away_team": "A" if i % 2 else "H",
            "home_score": 20 + (i * 7) % 13, "away_score": 22 + (i * 3) % 11,
            "neutral_site": False,
        } for year in range(2021, 2027) for i in range(140)],
    }


@pytest.mark.parametrize("sport", ["nfl", "mlb"])
def test_future_outcomes_and_same_day_result_do_not_leak(sport):
    original = history(sport)
    before, admitted = feature_rows(original, sport)
    changed = deepcopy(original)
    # Change 2026, which must not contribute even to current feature state.
    for game in changed["games"]:
        if game["season"] == 2026:
            game["home_score"] = 999
    after, admitted_after = feature_rows(changed, sport)
    assert checksum(admitted_after) == checksum(admitted)
    assert after == before
    target = next(r for r in before if r["game"]["game_id"] == "2025-40")
    early = dict(target["game"], game_id="same-day", home_score=100)
    early["starts_at"] = (datetime.fromisoformat(early["starts_at"]) - timedelta(hours=1)).isoformat()
    changed["games"].append(early)
    for game in changed["games"]:
        if game["starts_at"] >= target["game"]["starts_at"]:
            game["home_score"] = 88
    after, _ = feature_rows(changed, sport)
    actual = next(r for r in after if r["game"]["game_id"] == target["game"]["game_id"])
    assert actual["form_elo"] == target["form_elo"]


def test_missing_history_ties_duplicate_and_boundary_guards():
    payload = history()
    payload["games"][30]["away_score"] = payload["games"][30]["home_score"]
    rows, _ = feature_rows(payload, "nfl")
    assert next(r for r in rows if r["game"]["game_id"] == "2021-30")["outcome"] is None
    with pytest.raises(ValueError, match="Duplicate"):
        feature_rows(dict(payload, games=payload["games"] + [payload["games"][0]]), "nfl")
    assert feature_rows(dict(payload, games=payload["games"][:4]), "nfl")[0] == []
    groups = partitions(rows)
    groups["fit"][-1]["game"]["starts_at"] = groups["selection"][0]["game"]["starts_at"]
    with pytest.raises(ValueError, match="split boundary"):
        partitions(rows)
    with pytest.raises(ValueError, match="100 decisive"):
        partitions(rows[:10])


def test_paired_comparison_counts_only_matched_games_and_preserves_direction():
    rows, _ = feature_rows(history(), "nfl")
    rows = [r for r in rows[:100] if r["outcome"] is not None]
    p = [0.9 if r["outcome"] else 0.1 for r in rows]
    q = [0.5 if i % 2 else None for i, _ in enumerate(rows)]
    report = paired_comparison(rows, p, q)
    assert report["n"] == sum(v is not None for v in q)
    assert report["candidate"]["n"] == report["reference"]["n"] == report["n"]
    assert report["difference"]["brier"]["mean"] == pytest.approx(-0.24)
    assert report["difference"]["brier"]["weekly_bootstrap_95_percent_interval"] == pytest.approx([-0.24, -0.24])
    absent = paired_comparison(rows, p, [None] * len(rows))
    assert absent["n"] == 0 and absent["difference"] is None
    with pytest.raises(ValueError, match="Invalid"):
        paired_comparison(rows, [float("nan")] * len(rows), [0.5] * len(rows))


def test_diagnostic_labels_cannot_select_or_fit_and_artifact_replays(tmp_path):
    import hashlib

    payload = history()
    fixture = Path(__file__).parents[1] / "src/jabazi/models/artifacts/nfl_scores.json"
    source, comparator = tmp_path / "history.json", tmp_path / "reference.json"

    def run(data, label):
        source.write_text(json.dumps(data))
        reference = json.loads(fixture.read_text())
        reference["source_checksum"] = hashlib.sha256(source.read_bytes()).hexdigest()
        comparator.write_text(json.dumps(reference))
        report = train(source, tmp_path / label, "nfl", comparator)
        artifact = json.loads((tmp_path / label / "artifact.json").read_text())
        return report, artifact

    report, artifact = run(payload, "first")
    assert not report["approved_for_betting"] and not artifact["approved_for_betting"]
    assert report["paired_market_reference"]["n"] == 0
    assert report["execution_backtest"]["roi"] is None
    changed = deepcopy(payload)
    for game in changed["games"]:
        if game["season"] == 2025:
            game["home_score"], game["away_score"] = game["away_score"], game["home_score"]
    second, second_artifact = run(changed, "second")
    assert second["selected"] == report["selected"]
    assert second["selection_trials"] == report["selection_trials"]
    for key in ("mean", "scale", "coefficients", "intercept", "calibration_slope", "calibration_intercept"):
        assert artifact[key] == second_artifact[key]
    predictions = json.loads((tmp_path / "first/diagnostic_predictions.json").read_text())
    generated, _ = feature_rows(payload, "nfl")
    row = next(r for r in generated if r["game"]["game_id"] == predictions[0]["game_id"])
    z = artifact["intercept"] + sum(c * (x - mean) / scale for c, x, mean, scale in zip(
        artifact["coefficients"], row[artifact["family"]], artifact["mean"], artifact["scale"], strict=True))
    expected = 1 / (1 + math.exp(-(artifact["calibration_intercept"] + artifact["calibration_slope"] * z)))
    assert predictions[0]["probability"] == pytest.approx(expected, abs=1e-12)
    bad = json.loads(comparator.read_text())
    bad["source_checksum"] = "wrong"
    comparator.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="source or sport"):
        train(source, tmp_path / "bad", "nfl", comparator)

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from jabazi.models.game_distribution import GameDistribution
from jabazi.models.score_distribution import available_at
from jabazi.research.opponent_scores import design, fit_scores, joint_calibrate, samples, split_fold, matched_baseline


def rows(n=500):
    return [{"game": {"game_id": str(i), "starts_at": (datetime(2021, 1, 1, tzinfo=UTC)+timedelta(days=i)).isoformat(),
             "home_team": "A", "away_team": "B", "home_score": 20+i%13, "away_score": 15+i%17,
             "neutral_site": False}, "features": [20, 20, 20, 20, 0, 1]} for i in range(n)]


def test_disjoint_game_splits_and_label_availability():
    data = rows()
    cutoff = datetime(2022, 5, 16, tzinfo=UTC)
    train, residual, cal = split_fold(data, cutoff, 110)
    ids = [{r["game"]["game_id"] for r in part} for part in (train, residual, cal)]
    assert not (ids[0]&ids[1] or ids[1]&ids[2] or ids[0]&ids[2])
    assert max(available_at(r["game"]) for r in train) < min(datetime.fromisoformat(r["game"]["starts_at"]) for r in residual)
    assert max(available_at(r["game"]) for r in residual) < min(datetime.fromisoformat(r["game"]["starts_at"]) for r in cal)
    assert max(available_at(r["game"]) for r in cal) < cutoff
    with pytest.raises(ValueError):
        split_fold(data[:100], cutoff, 110)
    with pytest.raises(ValueError, match="Future label"):
        fit_scores(data, datetime(2021, 6, 1, tzinfo=UTC), "nfl")


def test_offense_defense_orientation_and_home_field():
    r = rows(1)
    matrix = design(r, ["A", "B"])
    assert matrix[0].tolist() == [1, 0, 0, 1, 1, 0]
    assert matrix[1].tolist() == [0, 1, 1, 0, -1, 0]
    r[0]["game"]["neutral_site"] = True
    assert not design(r, ["A", "B"])[:, -2].any()
    with pytest.raises(ValueError, match="team identity"):
        design(r, ["A", "C"])


def test_frozen_baseline_requires_same_game_results_and_fold():
    row = rows(1)[0]
    frozen = {"game": dict(row["game"]), "fold": "2021-01", "raw": {"moneyline": .5}}
    assert matched_baseline(row, frozen) == {"moneyline": .5}
    frozen["game"]["home_score"] += 1
    with pytest.raises(ValueError, match="identity/result mismatch"):
        matched_baseline(row, frozen)


def test_joint_calibration_preserves_coherent_ladders():
    rng = np.random.default_rng(1)
    residual = rng.multivariate_normal([0, 0], [[20, 4], [4, 15]], size=150)
    errors = rng.multivariate_normal([1, -1], [[30, 8], [8, 10]], size=150)
    adjusted = joint_calibrate(residual, errors)
    assert adjusted.mean(axis=0) == pytest.approx(errors.mean(axis=0))
    covariance = np.cov(errors, rowvar=False)
    assert np.cov(adjusted, rowvar=False) == pytest.approx(.9*covariance+.1*np.diag(np.diag(covariance)))
    distribution = GameDistribution(tuple(map(tuple, samples([24, 20], adjusted).tolist())))
    assert distribution.validate_ladders("A", "B")
    summary = distribution.summary()
    assert summary["expected_total"] == pytest.approx(summary["expected_home_points"]+summary["expected_away_points"])
    assert summary["total_variance"] == pytest.approx(summary["home_variance"]+summary["away_variance"]+2*summary["score_covariance"])


@pytest.mark.parametrize("bad", [np.zeros((100,2)), np.ones((99,2)), np.full((100,2), np.nan)])
def test_bad_residual_support_rejected(bad):
    with pytest.raises(ValueError):
        joint_calibrate(bad, np.random.default_rng(1).normal(size=(150,2)))

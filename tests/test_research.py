from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import math
import pytest

from jabazi.research.distributions import (
    empirical,
    poisson_count,
    usage_mixture,
    anytime_td,
    alternatives,
)
from jabazi.research.evaluation import Observation, chronological_split, evaluate, fit_isotonic


def obs(p, outcome, day=1):
    t = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Observation(p, outcome, t, t + timedelta(hours=1), t + timedelta(hours=5), "test-v1")


def test_integer_threshold_retains_push_mass_and_usage_uncertainty():
    active = empirical(
        [10, 20, 30], [".2", ".5", ".3"], model_version="test", provenance="SYNTHETIC TEST"
    )
    inactive = empirical([0], [1], model_version="test", provenance="SYNTHETIC TEST")
    mixture = usage_mixture(
        [active, inactive], [".8", ".2"], model_version="test", provenance="SYNTHETIC TEST"
    )
    assert mixture.threshold(20) == {"over": D(".24"), "under": D(".36"), "push": D(".40")}
    assert not mixture.approved_for_betting


def test_touchdown_model_uses_scoring_intensity():
    result = anytime_td(3, ".2", model_version="test", provenance="SYNTHETIC TEST")
    assert float(result["probability"]) == pytest.approx(1 - math.exp(-0.6))
    assert not result["approved_for_betting"]
    distribution = poisson_count(".6", model_version="test", provenance="SYNTHETIC TEST")
    assert float(distribution.threshold(".5")["over"]) == pytest.approx(
        float(result["probability"])
    )
    with pytest.raises(ValueError):
        poisson_count(20, model_version="test", provenance="test", max_count=2)


def test_alternates_rank_value_instead_of_hit_rate():
    distribution = empirical(
        [0, 10, 20], [".2", ".3", ".5"], model_version="test", provenance="SYNTHETIC TEST"
    )
    offers = [
        {"line": 5, "side": "over", "market_probability": ".8", "decimal_odds": "1.1"},
        {"line": 15, "side": "over", "market_probability": ".45", "decimal_odds": "2.3"},
    ]
    result = alternatives(distribution, offers)
    assert result[0]["offer"]["line"] == 15
    assert result[0]["status"] == "RESEARCH_ONLY"


def test_chronological_split_and_leakage_rejection():
    rows = [obs(0.5, 1, day) for day in (1, 4, 7)]
    a, b, c = chronological_split(
        rows, datetime(2025, 1, 4, tzinfo=UTC), datetime(2025, 1, 7, tzinfo=UTC)
    )
    assert [len(x) for x in (a, b, c)] == [1, 1, 1]
    with pytest.raises(ValueError):
        Observation(
            0.5, 1, rows[0].starts_at, rows[0].predicted_at, rows[0].result_available_at, "test"
        )


def test_probability_scoring_against_reference():
    result = evaluate([obs(0.8, 1), obs(0.2, 0)])
    assert result["brier"] == pytest.approx(0.04)
    assert result["log_loss"] == pytest.approx(-math.log(0.8))
    assert result["roc_auc"] == 1
    assert sum(b["n"] for b in result["reliability"]) == 2


def test_calibration_cannot_see_future_or_cross_model_versions():
    rows = [obs(0.2, 1), obs(0.4, 0), obs(0.8, 1)]
    at = datetime(2025, 2, 1, tzinfo=UTC)
    calibration = fit_isotonic(rows, fitted_at=at, minimum_samples=3)
    assert calibration.predict(0.2, at, "test-v1") == 0.5
    assert calibration.predict(0.4, at, "test-v1") == 0.5
    assert calibration.predict(0.8, at, "test-v1") == 1
    with pytest.raises(ValueError):
        calibration.predict(0.2, at, "test-v2")
    with pytest.raises(ValueError):
        calibration.predict(0.2, at - timedelta(days=1), "test-v1")
    with pytest.raises(ValueError):
        fit_isotonic(rows, fitted_at=rows[0].predicted_at, minimum_samples=3)
    with pytest.raises(ValueError):
        fit_isotonic(rows, fitted_at=at)

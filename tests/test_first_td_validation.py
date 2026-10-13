"""First TD categorical calibration tests. Synthetic records are never picks."""
from datetime import UTC, datetime, timedelta

import pytest

from jabazi.models.first_td_validation import (
    FirstTDValidationError, evaluate_frozen_forecasts, fair_american,
)


def _record(i=1):
    start = datetime(2026, 10, 12, 20, 0, tzinfo=UTC) + timedelta(days=i)
    return {
        "event_id": f"synthetic-{i}", "model_version": "SYNTHETIC_ONLY",
        "forecast_at": (start - timedelta(hours=4)).isoformat(),
        "starts_at": start.isoformat(),
        "probabilities": {"Home|Runner": .4, "Away|Receiver": .3,
                          "OTHER_OR_DEFENSE_ST": .2, "NO_TD": .1},
        "actual": "Home|Runner",
    }


def test_first_td_categorical_scores_and_fair_odds():
    result = evaluate_frozen_forecasts([_record(1), _record(2)], minimum_games=3)
    assert result["state"] == "INSUFFICIENT_SAMPLE"
    assert result["approved_for_betting"] is False
    assert result["sample_count"] == 2
    assert result["top_outcome_accuracy"] == 1
    assert result["multiclass_brier_score"] == pytest.approx(.50)
    assert result["multiclass_log_loss"] == pytest.approx(.916290731874155)
    assert result["top_outcome_calibration"][0]["mean_confidence"] == pytest.approx(.4)
    assert fair_american(.14) == 614
    assert fair_american(.6) == -150


@pytest.mark.parametrize("change", [
    {"forecast_at": "2026-10-14T20:00:00+00:00"},
    {"probabilities": {"Home|Runner": .7, "Away|Receiver": .2, "NO_TD": .2}},
    {"probabilities": {"Home|Runner": .5, "Away|Receiver": .5}},
    {"actual": "Unknown Player"},
    {"event_id": ""},
    {"model_version": ""},
])
def test_first_td_invalid_evidence_fails_closed(change):
    row = {**_record(), **change}
    with pytest.raises(FirstTDValidationError):
        evaluate_frozen_forecasts([row])


def test_first_td_rejects_duplicate_games_and_missing_history():
    with pytest.raises(FirstTDValidationError):
        evaluate_frozen_forecasts([_record(), _record()])
    empty = evaluate_frozen_forecasts([], minimum_games=100)
    assert empty["state"] == "INSUFFICIENT_SAMPLE"
    assert empty["multiclass_log_loss"] is None
    assert empty["approved_for_betting"] is False

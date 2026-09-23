from copy import deepcopy

import pytest

from jabazi.research.prop_data import inspect_prop_dataset


def dataset():
    return {
        "manifest": {
            "sport": "baseball_mlb",
            "market": "pitcher_strikeouts",
            "provider": "SYNTHETIC_TEST_ONLY",
            "data_mode": "real",
            "source_checksum": "TEST",
            "research_rights_reference": "TEST_FIXTURE_NOT_A_LICENSE",
        },
        "rows": [
            {
                "event_id": str(year),
                "player_id": "TEST_PLAYER",
                "prediction_at": f"{year}-06-01T10:00:00Z",
                "starts_at": f"{year}-06-01T12:00:00Z",
                "features_available_at": f"{year}-06-01T09:00:00Z",
                "result_available_at": f"{year}-06-01T16:00:00Z",
                "result_status": "final",
                "observed_value": 5,
                "features": {"prior_k_rate": 0.22},
                "expected_opportunities": 23,
            }
            for year in (2023, 2024, 2025)
        ],
    }


def inspect(data, minimum=1):
    return inspect_prop_dataset(
        data,
        train_before="2024-01-01T00:00:00Z",
        test_before="2025-01-01T00:00:00Z",
        minimum_per_split=minimum,
    )


def test_schema_admission_does_not_invent_a_trained_prop_model():
    report = inspect(dataset())
    assert report["counts"] == {"train": 1, "calibration": 1, "test": 1}
    assert report["status"] == "READY_FOR_RESEARCH_FIT"
    assert not report["approved_for_betting"] and not report["trained_model_available"]
    assert inspect(dataset(), minimum=100)["status"] == "INSUFFICIENT_DATA"


@pytest.mark.parametrize("mode", ["scrambled", "trial", "replay", "unknown", None])
def test_non_real_data_is_rejected(mode):
    data = dataset()
    data["manifest"]["data_mode"] = mode
    with pytest.raises(ValueError):
        inspect(data)


@pytest.mark.parametrize(
    "change",
    [
        {"features_available_at": "2023-06-01T13:00:00Z"},
        {"result_available_at": "2024-01-01T00:00:00Z"},
        {"prediction_at": "2023-06-01T10:00:00"},
        {"features": {"prior_k_rate": float("nan")}},
        {"observed_value": -1},
        {"observed_value": 1.5},
        {"result_status": "pending"},
    ],
)
def test_future_missing_or_invalid_training_evidence_is_rejected(change):
    data = dataset()
    data["rows"][0].update(change)
    with pytest.raises(ValueError):
        inspect(data)


def test_duplicate_athletes_and_games_cannot_inflate_the_sample():
    data = dataset()
    data["rows"].append(deepcopy(data["rows"][0]))
    with pytest.raises(ValueError):
        inspect(data)


def test_dnp_is_not_counted_as_a_zero_outcome():
    data = dataset()
    data["rows"][0].update(result_status="dnp", observed_value=None)
    report = inspect(data)
    assert report["counts"]["train"] == 0 and report["excluded"] == {"dnp": 1}
    assert report["status"] == "INSUFFICIENT_DATA"


def test_college_props_and_td_yardage_reuse_are_not_admitted():
    for sport, market in [
        ("americanfootball_ncaaf", "player_pass_yds"),
        ("americanfootball_nfl", "player_anytime_td"),
    ]:
        data = dataset()
        data["manifest"].update(sport=sport, market=market)
        with pytest.raises(ValueError):
            inspect(data)

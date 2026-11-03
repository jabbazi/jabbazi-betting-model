from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from jabazi.research.nfl_challenger import available_at, feature_rows


def payload():
    start = datetime(2021, 9, 1, 18, tzinfo=UTC)
    return {
        "sport": "americanfootball_nfl",
        "games": [
            {
                "game_id": str(i),
                "season": 2021,
                "starts_at": (start + timedelta(days=7 * i)).isoformat(),
                "home_team": "Home",
                "away_team": "Away",
                "home_score": 20 + i,
                "away_score": 15,
                "neutral_site": False,
            }
            for i in range(8)
        ],
    }


def test_current_and_future_results_do_not_change_earlier_features():
    data = payload()
    original = feature_rows(data)
    changed = deepcopy(data)
    for game in changed["games"][5:]:
        game["home_score"] = 80
    mutated = feature_rows(changed)
    assert [r["features"] for r in original[:2]] == [r["features"] for r in mutated[:2]]
    assert original[-1]["features"] != mutated[-1]["features"]
    for row in original:
        assert row["feature_available_at"] < row["game"]["starts_at"]


def test_missing_form_has_no_synthetic_features():
    data = payload()
    assert len(feature_rows(data)) == 4
    data["games"] = data["games"][:4]
    assert feature_rows(data) == []


def test_same_day_result_is_not_available_to_later_game():
    data = payload()
    early = deepcopy(data["games"][4])
    early.update(
        game_id="early",
        home_score=99,
        starts_at=(datetime.fromisoformat(early["starts_at"]) - timedelta(hours=3)).isoformat(),
    )
    baseline = feature_rows(data)[0]["features"]
    data["games"].append(early)
    row = next(r for r in feature_rows(data) if r["game"]["game_id"] == "4")
    assert row["features"] == baseline


def test_ties_not_relabelled_as_losses_and_duplicates_rejected():
    data = payload()
    data["games"][4]["away_score"] = data["games"][4]["home_score"]
    assert feature_rows(data)[0]["outcome"] is None
    data["games"].append(data["games"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        feature_rows(data)


def test_availability_proxy_waits_two_utc_boundaries():
    assert available_at(payload()["games"][0]) == datetime(2021, 9, 3, tzinfo=UTC)

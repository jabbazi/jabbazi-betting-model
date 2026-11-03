from datetime import UTC, datetime, timedelta

from jabazi.research.nba_player_experiment import build_dataset, build_datasets


def rows():
    base = datetime(2023, 10, 20, 23, tzinfo=UTC)
    result = []
    for i in range(8):
        start = base + timedelta(days=3 * i)
        result.append({
            "event_id": f"nba-{i}",
            "player_id": "p1",
            "participant": "Test Player",
            "starts_at": start.isoformat(),
            "result_available_at": (start + timedelta(hours=12)).isoformat(),
            "minutes": 30 + i % 3,
            "is_home": bool(i % 2),
            "points": 20 + i,
            "rebounds": 5 + i % 4,
            "assists": 4 + i % 3,
            "threes": 2,
            "blocks": i % 2,
            "steals": (i + 1) % 2,
            "turnovers": 2 + i % 2,
        })
    return result


def build(market):
    return build_dataset(
        rows=rows(),
        market=market,
        provider="TEST_ONLY",
        source_checksum="test-checksum",
        research_rights_reference="test fixture",
    )


def test_nba_dataset_is_causal_and_minutes_aware():
    document = build("player_points")
    assert len(document["rows"]) == 3
    first = document["rows"][0]
    assert first["observed_value"] == 25
    assert first["features"]["mean5_points"] == 22
    assert first["features"]["games_prior"] == 5
    assert first["features_available_at"] < first["prediction_at"] < first["starts_at"]
    assert first["expected_opportunities"] >= 30
    assert first["market_no_vig_probability"] is None


def test_nba_combo_targets_share_same_observed_box_score():
    pra = build("player_points_rebounds_assists")["rows"][0]
    pr = build("player_points_rebounds")["rows"][0]
    pa = build("player_points_assists")["rows"][0]
    ra = build("player_rebounds_assists")["rows"][0]
    assert pra["event_id"] == pr["event_id"] == pa["event_id"] == ra["event_id"]
    current = rows()[5]
    assert pra["observed_value"] == current["points"] + current["rebounds"] + current["assists"]
    assert pr["observed_value"] == current["points"] + current["rebounds"]
    assert pa["observed_value"] == current["points"] + current["assists"]
    assert ra["observed_value"] == current["rebounds"] + current["assists"]


def test_nba_double_double_is_binary_target():
    document = build("player_double_double")
    assert {row["observed_value"] for row in document["rows"]} <= {0, 1}


def test_multi_market_builder_matches_single_market_contract():
    multi = build_datasets(
        rows=rows(),
        markets=("player_points", "player_assists", "player_double_double"),
        provider="TEST_ONLY",
        source_checksum="test-checksum",
        research_rights_reference="test fixture",
    )
    assert multi["player_points"] == build("player_points")
    assert multi["player_assists"] == build("player_assists")
    assert multi["player_double_double"] == build("player_double_double")

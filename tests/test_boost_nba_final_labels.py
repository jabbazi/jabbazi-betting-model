from datetime import UTC, datetime, timedelta

import pytest

from jabazi.boost_identity_manifest import crosswalk_digest
from jabazi.boost_nba_final_labels import NBA_MARKETS, prepare_nba_final_labels

NOW = datetime(2026, 10, 29, 21, tzinfo=UTC)
START = NOW - timedelta(hours=4)


def game(**changes):
    row = {"id": 77, "datetime": START.isoformat(), "status_state": "final"}
    row.update(changes)
    return row


def stat(**changes):
    row = {
        "game": {"id": 77}, "player": {"id": 19},
        "min": "35:21", "pts": 24, "reb": 12, "ast": 4,
        "fg3m": 3, "blk": 1, "stl": 2, "turnover": 3,
    }
    row.update(changes)
    return row


def crosswalk(**changes):
    row = {
        "sport": "NBA", "bdl_game_id": 77, "bdl_player_id": 19,
        "source_namespace": "ESPN", "source_player_id": "PRIVATE_ESPN_ID",
        "source_record_sha256": "a" * 64,
        "canonical_event_id": "PRIVATE_CANONICAL_EVENT",
        "canonical_participant": "PRIVATE_PLAYER_NAME",
        "event_starts_at": START.isoformat(),
        "reviewed_at": (START - timedelta(hours=1)).isoformat(),
        "independent_source_reviewed": True,
    }
    row.update(changes)
    row["record_sha256"] = crosswalk_digest(row)
    return row


def check(g=None, stats=None, crosswalks=None):
    return prepare_nba_final_labels(
        game() if g is None else g,
        [stat()] if stats is None else stats,
        [crosswalk()] if crosswalks is None else crosswalks,
        observed_at=NOW,
    )


def test_final_nba_boxscore_uses_training_target_contract_for_all_markets():
    report = check()
    assert report["final_players_prepared"] == 1
    assert report["final_market_labels_prepared"] == len(NBA_MARKETS) == 12
    rows = {r["market"]: r for r in report["_private_result_rows"]}
    assert rows["player_points"]["observed_value"] == 24
    assert rows["player_rebounds"]["observed_value"] == 12
    assert rows["player_points_rebounds_assists"]["observed_value"] == 40
    assert rows["player_double_double"]["observed_value"] == 1
    assert rows["player_threes"]["observed_value"] == 3
    assert all(len(row["source_checksum"]) == 64 for row in rows.values())
    assert report["prospective_calibration_validated"] is False
    assert report["production_approved"] is False
    safe = dict(report)
    safe.pop("_private_result_rows")
    assert "PRIVATE_PLAYER_NAME" not in str(safe)


@pytest.mark.parametrize("change", [
    {"min": None}, {"min": "0:00"}, {"min": "DNP"},
    {"turnover": None}, {"fg3m": None},
    {"pts": -1}, {"pts": 2, "fg3m": 3},
])
def test_dnp_missing_stats_or_incoherent_boxscore_not_zero_filled(change):
    report = check(stats=[stat(**change)])
    assert report["final_market_labels_prepared"] == 0


def test_duplicate_final_player_stats_never_select_first():
    report = check(stats=[stat(), stat(pts=30)])
    assert report["final_market_labels_prepared"] == 0
    assert report["rejections"]["duplicate_player_stat"] == 2


@pytest.mark.parametrize("change", [
    {"bdl_player_id": 20},
    {"canonical_event_id": ""},
    {"source_namespace": "NFLVERSE"},
    {"independent_source_reviewed": False},
    {"reviewed_at": (START + timedelta(minutes=1)).isoformat()},
    {"event_starts_at": (START + timedelta(hours=1)).isoformat()},
])
def test_unverified_or_postgame_identity_mapping_cannot_grade(change):
    assert check(crosswalks=[crosswalk(**change)])["final_market_labels_prepared"] == 0


def test_modified_crosswalk_fingerprint_rejected():
    cw = crosswalk()
    cw["canonical_participant"] = "CHANGED"
    assert check(crosswalks=[cw])["final_market_labels_prepared"] == 0


@pytest.mark.parametrize("change", [
    {"status_state": "scheduled"},
    {"status_state": "in_progress"},
    {"datetime": (NOW + timedelta(hours=1)).isoformat()},
])
def test_nonfinal_game_cannot_settle(change):
    with pytest.raises(ValueError):
        check(g=game(**change))


def test_foreign_game_and_player_stats_fail_closed():
    report = check(stats=[stat(game={"id": 999})])
    assert report["final_market_labels_prepared"] == 0
    assert report["rejections"]["foreign_game_or_player_stat"] == 1

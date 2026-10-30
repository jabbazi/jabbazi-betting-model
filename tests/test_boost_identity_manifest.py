from datetime import UTC, datetime, timedelta

import pytest

from jabazi.boost_identity_manifest import audit_identity_manifest, crosswalk_digest

NOW = datetime(2026, 10, 29, 21, tzinfo=UTC)


def record(sport="NBA", **changes):
    row = {
        "sport": sport, "bdl_game_id": 77, "bdl_player_id": 19,
        "source_namespace": "ESPN" if sport == "NBA" else "NFLVERSE",
        "source_player_id": "espn-456" if sport == "NBA" else "nflverse-456",
        "team_id": "T1",
        "event_starts_at": (NOW + timedelta(hours=2)).isoformat(),
        "reviewed_at": (NOW - timedelta(hours=1)).isoformat(),
        "source_record_sha256": "a" * 64,
        "independent_source_reviewed": True,
    }
    row.update(changes)
    row["record_sha256"] = crosswalk_digest(row)
    return row


def test_valid_structure_still_not_independently_authenticated():
    report = audit_identity_manifest("NBA", [record()], observed_at=NOW)
    assert report["unique_structurally_valid_crosswalks"] == 1
    assert report["independent_provider_truth_confirmed_by_runtime"] is False
    assert report["hit_probability_verified"] is False
    assert report["betting_enabled"] is False


def test_nfl_namespace_is_distinct():
    report = audit_identity_manifest("NFL", [record("NFL")], observed_at=NOW)
    assert report["unique_structurally_valid_crosswalks"] == 1
    assert audit_identity_manifest("NBA", [record("NFL")], observed_at=NOW)["unique_structurally_valid_crosswalks"] == 0


@pytest.mark.parametrize("change", [
    {"bdl_player_id": None}, {"bdl_game_id": 0},
    {"source_namespace": "BALLDONTLIE"},
    {"source_player_id": ""}, {"team_id": ""},
    {"reviewed_at": (NOW + timedelta(minutes=1)).isoformat()},
    {"event_starts_at": (NOW - timedelta(minutes=1)).isoformat()},
    {"source_record_sha256": "bad"},
    {"independent_source_reviewed": False},
])
def test_invalid_provenance_rejected(change):
    report = audit_identity_manifest("NBA", [record(**change)], observed_at=NOW)
    assert report["unique_structurally_valid_crosswalks"] == 0


def test_mutation_after_hashing_rejected():
    row = record()
    row["source_player_id"] = "different"
    report = audit_identity_manifest("NBA", [row], observed_at=NOW)
    assert report["rejections"]["crosswalk_fingerprint_mismatch"] == 1


def test_duplicate_or_conflicting_identity_rejected():
    report = audit_identity_manifest("NBA", [record(), record(source_player_id="another")],
                                     observed_at=NOW)
    assert report["unique_structurally_valid_crosswalks"] == 0
    assert report["rejections"]["duplicate_or_conflicting_crosswalk"] == 1


def test_private_identity_never_leaks():
    report = audit_identity_manifest("NBA", [record(source_player_id="PRIVATE_PLAYER")],
                                     observed_at=NOW)
    assert "PRIVATE_PLAYER" not in str(report)


def test_unsupported_sport_and_naive_time_fail():
    with pytest.raises(ValueError):
        audit_identity_manifest("NHL", [], observed_at=NOW)
    with pytest.raises(ValueError):
        audit_identity_manifest("NBA", [], observed_at=datetime(2026, 10, 29))

from datetime import UTC, datetime, timedelta

import pytest

from jabazi.boost_roster_candidates import (
    match_roster_candidates, redacted_candidate_summary,
)

NOW = datetime(2026, 10, 29, 21, tzinfo=UTC)
KICKOFF = (NOW + timedelta(hours=3)).isoformat()
OBSERVED = (NOW - timedelta(minutes=10)).isoformat()


def bdl(sport="NBA", **kw):
    row = {"id": 77, "first_name": "Shai", "last_name": "Gilgeous-Alexander",
           "jersey_number": "02",
           "team": {"abbreviation": "OKC"},
           "position_abbreviation": "QB" if sport == "NFL" else "G"}
    row.update(kw)
    return row


def source(sport="NBA", **kw):
    row = {"source_namespace": "ESPN" if sport == "NBA" else "NFLVERSE",
           "source_player_id": "espn-5" if sport == "NBA" else "nflverse-5",
           "full_name": "Shai Gilgeous Alexander", "team_abbreviation": "OKC",
           "jersey_number": 2, "source_observed_at": OBSERVED,
           "position_abbreviation": "QB" if sport == "NFL" else "PG"}
    row.update(kw)
    return row


def check(bdl_rows=None, source_rows=None, sport="NBA"):
    return match_roster_candidates(
        sport, [bdl()] if bdl_rows is None else bdl_rows,
        [source()] if source_rows is None else source_rows,
        observed_at=NOW, event_starts_at=KICKOFF,
    )


def test_nba_exact_name_team_jersey_is_candidate_only():
    report = check()
    assert report["candidate_count"] == 1
    candidate = report["candidates_private"][0]
    assert candidate["bdl_player_id"] == 77
    assert candidate["source_namespace"] == "ESPN"
    assert candidate["provider_identity_verified"] is False
    assert candidate["independent_source_reviewed"] is False
    assert report["independently_verified_crosswalks"] == 0
    assert report["model_probabilities_verified"] is False
    assert report["betting_enabled"] is False


def test_nfl_requires_exact_position_as_well():
    assert check([bdl("NFL")], [source("NFL")], "NFL")["candidate_count"] == 1
    report = check([bdl("NFL")], [source("NFL", position_abbreviation="WR")], "NFL")
    assert report["candidate_count"] == 0
    assert report["rejections"]["nfl_position_conflict"] == 1


@pytest.mark.parametrize("changes", [
    {"jersey_number": "3"},
    {"team": {"abbreviation": "BOS"}},
    {"last_name": "Smith"},
    {"jersey_number": None},
    {"team": None},
])
def test_missing_or_mismatched_bdl_factors_fail_closed(changes):
    assert check([bdl(**changes)])["candidate_count"] == 0


@pytest.mark.parametrize("changes", [
    {"source_namespace": "BALLDONTLIE"},
    {"source_player_id": ""},
    {"jersey_number": None},
    {"source_observed_at": (NOW - timedelta(days=3)).isoformat()},
    {"source_observed_at": (NOW + timedelta(seconds=1)).isoformat()},
])
def test_missing_or_stale_source_evidence_fails_closed(changes):
    assert check(source_rows=[source(**changes)])["candidate_count"] == 0


def test_ambiguous_name_team_jersey_never_picks_first():
    report = check(source_rows=[source(source_player_id="espn-5"),
                                source(source_player_id="espn-6")])
    assert report["candidate_count"] == 0
    assert report["rejections"]["ambiguous_identity_factors"] == 1


def test_duplicate_bdl_id_across_different_roster_keys_fails_closed():
    report = check(
        bdl_rows=[bdl(), bdl(team={"abbreviation": "BOS"})],
        source_rows=[source(), source(team_abbreviation="BOS", source_player_id="espn-6")],
    )
    assert report["candidate_count"] == 0
    assert report["rejections"]["cross_key_duplicate_player_identity"] == 2


def test_duplicate_source_id_across_different_roster_keys_fails_closed():
    report = check(
        bdl_rows=[bdl(), bdl(id=78, team={"abbreviation": "BOS"})],
        source_rows=[source(), source(team_abbreviation="BOS")],
    )
    assert report["candidate_count"] == 0


def test_redacted_summary_excludes_private_identity_and_source_records():
    report = check(bdl_rows=[bdl(first_name="PRIVATE", last_name="ATHLETE")],
                   source_rows=[source(full_name="PRIVATE ATHLETE",
                                       source_player_id="SECRET_SOURCE_ID")])
    assert report["candidate_count"] == 1
    safe = redacted_candidate_summary(report)
    assert "candidates_private" not in safe
    assert "SECRET_SOURCE_ID" not in str(safe)
    assert "PRIVATE" not in str(safe)
    assert safe["approval"] == "RESEARCH_ONLY"


def test_invalid_kickoff_and_sport_rejected():
    with pytest.raises(ValueError):
        match_roster_candidates("NHL", [], [], observed_at=NOW, event_starts_at=KICKOFF)
    with pytest.raises(ValueError):
        match_roster_candidates("NBA", [], [], observed_at=NOW,
                                event_starts_at=(NOW - timedelta(seconds=1)).isoformat())

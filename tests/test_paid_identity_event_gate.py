"""No candidate game check can imply an authenticated player identity."""
from datetime import UTC, datetime, timedelta
import pytest
from jabazi.paid_identity_event_gate import audit_candidate_game_context

NOW = datetime(2026, 11, 9, 5, tzinfo=UTC)
START = (NOW + timedelta(hours=3)).isoformat()


def candidate(sport="NHL", **kw):
    names = {"NHL": "NHL", "NBA": "ESPN", "NFL": "NFLVERSE"}
    row = {
        "sport": sport, "source_namespace": names[sport],
        "team_abbreviation": "NYR",
        "review_state": "CANDIDATE_REQUIRES_INDEPENDENT_VERIFICATION",
        "independent_source_reviewed": False,
        "provider_identity_verified": False,
        "review_evidence_private": {
            "team_abbreviation": "NYR", "event_starts_at": START,
            "bdl_player_name": "REDACT THIS NAME",
        },
    }
    row.update(kw)
    return row


def game(sport="NHL", **kw):
    time_field = {"NHL": "start_time_utc", "NBA": "datetime", "NFL": "date"}[sport]
    row = {"id": 15, "status_state": "scheduled",
           time_field: START, "away_team": {"tricode": "NYR"},
           "home_team": {"tricode": "BOS"}}
    row.update(kw)
    return row


@pytest.mark.parametrize("sport", ["NHL", "NBA", "NFL"])
def test_game_membership_candidate_only(sport):
    row = game(sport, away_team={"abbreviation": "NYR"},
               home_team={"abbreviation": "BOS"})
    result = audit_candidate_game_context(sport, row, [candidate(sport)], observed_at=NOW)
    assert len(result["private_event_membership_candidates"]) == 1
    safe = result["redacted_summary"]
    assert safe["structurally_game_eligible_candidate_count"] == 1
    assert safe["identities_independently_verified"] == 0
    assert safe["betting_enabled"] is False
    assert "REDACT THIS NAME" not in str(safe)


def test_wrong_team_or_kickoff_never_matches():
    mismatch = candidate(team_abbreviation="BUF")
    wrong_start = candidate(review_evidence_private={
        "team_abbreviation": "NYR",
        "event_starts_at": (NOW + timedelta(hours=2)).isoformat(),
    })
    result = audit_candidate_game_context("NHL", game(), [mismatch, wrong_start],
                                          observed_at=NOW)
    assert result["redacted_summary"]["structurally_game_eligible_candidate_count"] == 0
    assert result["redacted_summary"]["rejections"] == {
        "EVENT_KICKOFF_MISMATCH": 1, "PLAYER_TEAM_NOT_IN_GAME": 1,
    }


@pytest.mark.parametrize("change", [
    {"status_state": "in_progress"},
    {"start_time_utc": (NOW - timedelta(minutes=1)).isoformat()},
    {"start_time_utc": "2026-11-09T08:00:00"},
    {"home_team": None},
])
def test_unverified_game_fails_closed(change):
    out = audit_candidate_game_context("NHL", game(**change), [candidate()], observed_at=NOW)
    assert out["redacted_summary"]["structurally_game_eligible_candidate_count"] == 0


def test_never_accepts_self_asserted_approvals():
    result = audit_candidate_game_context("NHL", game(), [
        candidate(provider_identity_verified=True),
        candidate(independent_source_reviewed=True),
    ], observed_at=NOW)
    assert result["redacted_summary"]["structurally_game_eligible_candidate_count"] == 0
    assert result["redacted_summary"]["rejections"]["CANDIDATE_PROVENANCE_INVALID"] == 2


def test_unbounded_or_naive_observation_rejected():
    with pytest.raises(ValueError):
        audit_candidate_game_context("NHL", game(), [], observed_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        audit_candidate_game_context("NHL", game(), [candidate()] * 1001, observed_at=NOW)

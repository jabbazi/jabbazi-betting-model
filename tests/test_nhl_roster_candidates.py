"""NHL BDL-to-official roster matches are review CANDIDATES, never approvals."""
from datetime import UTC, datetime, timedelta
from jabazi.boost_roster_candidates import match_roster_candidates, redacted_candidate_summary
from jabazi.boost_nhl_official_roster import fetch_nhl_official_roster

NOW = datetime(2026, 11, 9, 5, tzinfo=UTC)
START = (NOW + timedelta(hours=3)).isoformat()


def bdl(**overrides):
    row = dict(id=184, full_name="Example Skater", position_code="LW",
               teams=[dict(tricode="NYR", season=2026)])
    row.update(overrides)
    return row


def official(**overrides):
    row = dict(source_namespace="NHL", source_player_id="998877",
               full_name="Example Skater", team_abbreviation="NYR",
               position_abbreviation="L", source_observed_at=NOW.isoformat(),
               source_response_sha256="f" * 64)
    row.update(overrides)
    return row


def candidates(players, roster):
    return match_roster_candidates(
        "NHL", players, roster, observed_at=NOW, event_starts_at=START,
    )


def test_exact_nhl_name_team_position_is_unapproved_candidate():
    result = candidates([bdl()], [official()])
    assert result["candidate_count"] == 1
    row = result["candidates_private"][0]
    assert row["match_factors"] == [
        "exact_normalized_name", "team_abbreviation", "position_abbreviation"
    ]
    assert row["independent_source_reviewed"] is False
    assert result["independently_verified_crosswalks"] == 0
    assert result["betting_enabled"] is False
    assert "998877" not in str(redacted_candidate_summary(result))


def test_nhl_team_trade_ambiguity_fails_closed():
    result = candidates([bdl(teams=[
        {"tricode": "NYR", "season": 2026},
        {"tricode": "BOS", "season": 2026},
    ])], [official()])
    assert result["candidate_count"] == 0


def test_nhl_missing_season_or_mismatched_position_fails_closed():
    assert candidates([bdl(teams=[{"tricode": "NYR", "season": 2025}])], [official()])["candidate_count"] == 0
    assert candidates([bdl(position_code="G")], [official()])["candidate_count"] == 0


def test_nhl_duplicate_candidates_fail_closed():
    assert candidates([bdl(), bdl()], [official()])["candidate_count"] == 0
    assert candidates([bdl()], [official(), official()])["candidate_count"] == 0


def test_official_nhl_roster_is_bounded_and_preserves_source_hash(monkeypatch):
    from jabazi import boost_nhl_official_roster as mod
    called = []
    def fake(url):
        called.append(url)
        return ({
            "forwards": [{"id": 998877, "firstName": {"default": "Example"},
                          "lastName": {"default": "Skater"}, "positionCode": "L"}],
            "defensemen": [], "goalies": [],
        }, "f" * 64)
    monkeypatch.setattr(mod, "_fetch_json", fake)
    rows = fetch_nhl_official_roster({"NYR"}, now=NOW)
    assert len(called) == 1 and len(rows) == 1
    assert rows[0]["source_player_id"] == "998877"
    assert rows[0]["source_response_sha256"] == "f" * 64

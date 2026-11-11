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


def test_nhl_original_birth_date_conflict_is_not_silently_normalized():
    result = candidates([bdl(birth_date="1997-07-14")], [official(birth_date="1997-07-15")])
    assert result["candidate_count"] == 0
    assert result["rejections"] == {"nhl_birth_date_conflict": 1}
    conflict = result['conflicts_private'][0]
    assert conflict['bdl_record']['birth_date'] == '1997-07-14'
    assert conflict['source_record']['birth_date'] == '1997-07-15'
    assert conflict['resolution'] == 'UNRESOLVED'
    assert conflict['provider_identity_verified'] is False
    public = redacted_candidate_summary(result)
    assert public['unresolved_identity_conflicts'] == 1
    assert '1997-07' not in str(public) and 'Example Skater' not in str(public)


def test_nhl_matching_birth_dates_remain_unapproved_review_evidence():
    result = candidates([bdl(birth_date="1997-07-15")], [official(birth_date="1997-07-15")])
    row=result["candidates_private"][0]
    assert row["review_evidence_private"]["bdl_birth_date"] == "1997-07-15"
    assert row["review_evidence_private"]["source_birth_date"] == "1997-07-15"
    assert row["independent_source_reviewed"] is False


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
    assert called[0].endswith("/roster/NYR/20262027")
    assert rows[0]["source_player_id"] == "998877"
    assert rows[0]["source_response_sha256"] == "f" * 64


def test_nhl_private_review_evidence_requires_actual_source_confirmation():
    report = candidates([bdl()], [official()])
    review = report["candidates_private"][0]["review_evidence_private"]
    assert review["bdl_player_name"] == "Example Skater"
    assert review["source_player_name"] == "Example Skater"
    assert review["team_abbreviation"] == "NYR"
    assert review["bdl_position"] == "LW"
    assert review["source_position"] == "L"
    assert review["bdl_jersey"] is None
    assert report["candidates_private"][0]["provider_identity_verified"] is False
    assert "Example Skater" not in str(redacted_candidate_summary(report))


def test_nhl_dated_roster_uses_prior_season_before_july(monkeypatch):
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
    from datetime import datetime, UTC
    rows = fetch_nhl_official_roster(
        {"LAK"}, now=datetime(2027, 1, 15, tzinfo=UTC)
    )
    assert len(rows) == 1
    assert called == [f"{mod.WEB_BASE}/roster/LAK/20262027"]


def test_nhl_dated_roster_changes_at_new_season(monkeypatch):
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
    from datetime import datetime, UTC
    fetch_nhl_official_roster({"LAK"}, now=datetime(2027, 10, 1, tzinfo=UTC))
    assert called == [f"{mod.WEB_BASE}/roster/LAK/20272028"]

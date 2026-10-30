from datetime import UTC, datetime

import pytest

from jabazi import boost_nba_espn_roster as roster


def test_fetch_bounded_espn_roster_from_verified_team_ids(monkeypatch):
    monkeypatch.setattr(
        roster.NBAPlayerFeatureCollector, "_team_index",
        lambda self: {"Oklahoma City Thunder": {"id": "25", "abbr": "OKC"}},
    )
    seen = []
    def fake_json(url):
        seen.append(url)
        return ({"athletes": [
            {"items": [{"id": "abc-1", "displayName": "Shai Gilgeous-Alexander",
                        "jersey": "2", "position": {"abbreviation": "PG"}}]}
        ]}, "a" * 64)
    monkeypatch.setattr(roster, "_json", fake_json)
    rows = roster.fetch_nba_espn_roster({"OKC"}, now=datetime.now(UTC))
    assert len(rows) == 1
    assert rows[0]["source_namespace"] == "ESPN"
    assert rows[0]["source_player_id"] == "abc-1"
    assert rows[0]["jersey_number"] == "2"
    assert rows[0]["source_response_sha256"] == "a" * 64
    assert seen == [roster.ESPN + "/teams/25/roster"]


def test_missing_team_fails_before_roster_requests(monkeypatch):
    monkeypatch.setattr(roster.NBAPlayerFeatureCollector, "_team_index", lambda self: {})
    monkeypatch.setattr(roster, "_json", lambda url: (_ for _ in ()).throw(AssertionError(url)))
    with pytest.raises(ValueError, match="Missing ESPN team"):
        roster.fetch_nba_espn_roster({"OKC"}, now=datetime.now(UTC))


@pytest.mark.parametrize("teams", [[], {"OKC", "BOS", "DAL", "MIA", "CHI"},
                                    {"??"}, {"OKC", "123"}])
def test_invalid_team_scope_rejected(teams):
    with pytest.raises(ValueError):
        roster.fetch_nba_espn_roster(teams, now=datetime.now(UTC))


def test_duplicate_team_abbreviation_rejected(monkeypatch):
    monkeypatch.setattr(roster.NBAPlayerFeatureCollector, "_team_index",
                        lambda self: {"A": {"id": "1", "abbr": "OKC"},
                                      "B": {"id": "2", "abbr": "OKC"}})
    with pytest.raises(ValueError, match="Ambiguous ESPN team"):
        roster.fetch_nba_espn_roster({"OKC"}, now=datetime.now(UTC))

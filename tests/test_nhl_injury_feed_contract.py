"""Exercise the team-filtered ESPN shape observed in the live runtime."""
import pytest

from jabazi.providers import nhl_player_features as nhlp


def evidence(monkeypatch, payload):
    monkeypatch.setattr(nhlp, "_fetch_json", lambda *a, **k: (payload, "checksum"))
    return nhlp.NHLPlayerFeatureCollector()._injury_evidence(
        {"team": "BOS", "name": "Fixture Player"}
    )


@pytest.mark.parametrize("grouped", [False, True])
def test_explicit_team_coverage_accepts_unlisted_player(monkeypatch, grouped):
    team = {"abbreviation": "BOS"}
    rows = [{"athlete": {"displayName": "Another Player"}, "status": "Out"}]
    payload = {"team": team, "injuries": rows, "status": "success"}
    if grouped:
        payload = {"injuries": [{"team": team, "injuries": rows}]}
    assert evidence(monkeypatch, payload)["available"] is True


@pytest.mark.parametrize("status", ["Out", "Injured Reserve", "Day-To-Day", "Unknown", "", None])
def test_listed_player_without_clearance_stays_unavailable(monkeypatch, status):
    result = evidence(monkeypatch, {
        "team": {"abbreviation": "BOS"},
        "injuries": [{"athlete": {"displayName": "Fixture Player"}, "status": status}],
    })
    assert result["available"] is False


@pytest.mark.parametrize("payload", [
    {"injuries": []},
    {"team": {"abbreviation": "NYR"}, "injuries": []},
    {"team": {"abbreviation": "BOS"}},
    {"team": {"abbreviation": "BOS"}, "injuries": [], "status": "error"},
    {"team": {"abbreviation": "BOS"}, "injuries": [{}]},
    {"team": {"abbreviation": "BOS"}, "injuries": [None]},
])
def test_missing_or_malformed_team_coverage_is_not_clearance(monkeypatch, payload):
    assert evidence(monkeypatch, payload) is None


def test_explicit_empty_team_report_is_supported(monkeypatch):
    assert evidence(monkeypatch, {
        "team": {"abbreviation": "BOS"}, "injuries": []
    })["available"] is True

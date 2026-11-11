"""Synthetic source-contract checks; not live model acceptance."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from jabazi.providers import nba_player_features as nba


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("status,available", [("Out", False), ("Questionable", False),
    ("Unknown", False), (None, False), ("Active", True)])
def test_team_injury_formats_and_uncertain_status(monkeypatch, grouped, status, available):
    team = {"abbreviation": "BOS"}
    rows = [{"athlete": {"displayName": "Fixture Player"}, "status": status}]
    payload = {"team": team, "injuries": rows}
    if grouped:
        payload = {"injuries": [{"team": team, "injuries": rows}]}
    monkeypatch.setattr(nba, "_json", lambda *a: (payload, "receipt"))
    result = nba.NBAPlayerFeatureCollector()._injury(
        {"team_abbr": "BOS", "name": "Fixture Player"})
    assert result["available"] is available


@pytest.mark.parametrize("payload", [{"injuries": []}, {},
    {"team": {"abbreviation": "NYK"}, "injuries": []},
    {"team": {"abbreviation": "BOS"}, "injuries": [None]},
    {"team": {"abbreviation": "BOS"}, "injuries": [], "status": "error"}])
def test_missing_team_coverage_never_means_available(monkeypatch, payload):
    monkeypatch.setattr(nba, "_json", lambda *a: (payload, "receipt"))
    assert nba.NBAPlayerFeatureCollector()._injury(
        {"team_abbr": "BOS", "name": "Fixture Player"}) is None


@pytest.mark.parametrize("wrong_id,recent", [(True, False), (False, True)])
def test_other_player_or_not_yet_available_history_is_excluded(monkeypatch, wrong_id, recent):
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    collector = nba.NBAPlayerFeatureCollector(now=now)
    player = {"player_id": "right", "team_name": "Boston Celtics",
              "team_abbr": "BOS", "checksum": "roster"}
    monkeypatch.setattr(collector, "_roster_player", lambda _: dict(player))
    rows = [{"player_id": "wrong" if wrong_id else "right", "participant": "Same Name",
             "start": now-timedelta(hours=1) if recent else now-timedelta(days=10+i),
             "minutes": 30} for i in range(6)]
    monkeypatch.setattr(collector, "_history_rows", lambda: (rows, "receipt"))
    card = SimpleNamespace(sport="basketball_nba", participant="Same Name", in_play=False,
                           starts_at=now+timedelta(hours=8), event_id="game")
    assert collector.snapshot(card) is None

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jabazi.providers.nba_player_features import NBAPlayerFeatureCollector
from jabazi.providers import nhl_player_features as nhlp


NOW = datetime(2026, 10, 20, 18, tzinfo=UTC)
START = NOW + timedelta(hours=6)


def nba_card():
    return SimpleNamespace(
        sport="basketball_nba",
        event_id="nba-live-1",
        event="New York Knicks @ Boston Celtics",
        market="player_points",
        participant="Jayson Tatum",
        in_play=False,
        starts_at=START,
        selection="Over",
        line=28.5,
        observed_at=NOW,
    )


def test_nba_live_snapshot_requires_roster_injury_and_rotation(monkeypatch):
    collector = NBAPlayerFeatureCollector(now=NOW)
    monkeypatch.setattr(
        collector,
        "_roster_player",
        lambda card: {
            "player_id": "4065648",
            "team_name": "Boston Celtics",
            "team_id": "2",
            "team_abbr": "BOS",
            "checksum": "roster",
            "name": card.participant,
        },
    )
    rows = []
    for i in range(8):
        rows.append({
            "participant": "Jayson Tatum",
            "player_id": "4065648",
            "start": NOW - timedelta(days=16 - i * 2),
            "minutes": 34 + (i % 3),
            "is_home": bool(i % 2),
            "points": 25 + i,
            "rebounds": 7,
            "assists": 5,
            "threes": 3,
            "blocks": 1,
            "steals": 1,
            "turnovers": 2,
        })
    monkeypatch.setattr(collector, "_history_rows", lambda: (rows, "history"))
    monkeypatch.setattr(
        collector,
        "_injury",
        lambda player: {
            "verified": True,
            "available": True,
            "status": "not_listed",
            "checksum": "injury",
        },
    )
    snap = collector.snapshot(nba_card())
    assert snap is not None
    assert snap["integrity"] == {
        "event_identity": True,
        "player_identity": True,
        "fresh_features": True,
        "schema": True,
        "role": True,
        "availability": True,
        "injuries": True,
        "no_duplicate_event": True,
    }
    assert snap["features"]["is_home"] == 1.0
    assert snap["features"]["mean5_minutes"] >= 34


def test_nba_live_snapshot_fails_closed_on_injury(monkeypatch):
    collector = NBAPlayerFeatureCollector(now=NOW)
    monkeypatch.setattr(
        collector,
        "_roster_player",
        lambda card: {
            "player_id": "4065648",
            "team_name": "Boston Celtics",
            "team_id": "2",
            "team_abbr": "BOS",
            "checksum": "roster",
            "name": card.participant,
        },
    )
    rows = [{
        "participant": "Jayson Tatum",
        "player_id": "4065648",
        "start": NOW - timedelta(days=10-i),
        "minutes": 35,
        "is_home": True,
        "points": 25,
        "rebounds": 7,
        "assists": 5,
        "threes": 3,
        "blocks": 1,
        "steals": 1,
        "turnovers": 2,
    } for i in range(6)]
    monkeypatch.setattr(collector, "_history_rows", lambda: (rows, "history"))
    monkeypatch.setattr(
        collector,
        "_injury",
        lambda player: {
            "verified": True,
            "available": False,
            "status": "out",
            "checksum": "injury",
        },
    )
    snap = collector.snapshot(nba_card())
    assert snap is not None
    assert snap["integrity"]["role"] is False
    assert snap["integrity"]["availability"] is False
    assert snap["integrity"]["injuries"] is False


def test_nhl_goalie_starter_gate_uses_explicit_game_flag(monkeypatch):
    card = SimpleNamespace(
        sport="icehockey_nhl",
        event_id="nhl-live-1",
        event="Florida Panthers @ Carolina Hurricanes",
        market="player_total_saves",
        participant="Sergei Bobrovsky",
        in_play=False,
        starts_at=START,
        selection="Over",
        line=27.5,
        observed_at=NOW,
    )
    player = {"name": "Sergei Bobrovsky", "team": "FLA"}

    def fetch(url, timeout=12):
        if "scoreboard?dates=" in url:
            return {
                "events": [{
                    "id": "401",
                    "competitions": [{
                        "competitors": [
                            {"team": {"displayName": "Florida Panthers"}},
                            {"team": {"displayName": "Carolina Hurricanes"}},
                        ]
                    }],
                }]
            }, "scoreboard"
        if "summary?event=401" in url:
            return {
                "boxscore": {
                    "players": [{
                        "statistics": [{
                            "athletes": [{
                                "starter": True,
                                "athlete": {"displayName": "Sergei Bobrovsky"},
                            }]
                        }]
                    }]
                }
            }, "summary"
        raise AssertionError(url)

    monkeypatch.setattr(nhlp, "_fetch_json", fetch)
    collector = nhlp.NHLPlayerFeatureCollector(now=NOW)
    evidence = collector._goalie_starter_evidence(card, player)
    assert evidence is not None
    assert evidence["starter"] is True
    assert evidence["verified"] is True

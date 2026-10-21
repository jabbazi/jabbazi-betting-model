from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jabazi.providers.player_features_live import LivePlayerFeatureCollector


NOW = datetime(2026, 9, 28, 20, tzinfo=UTC)


def nfl_card():
    return SimpleNamespace(
        sport="americanfootball_nfl",
        event_id="nfl-test",
        event="Philadelphia Eagles @ Chicago Bears",
        market="player_rush_attempts",
        participant="Test Runner",
        starts_at=NOW + timedelta(hours=5),
        in_play=False,
    )


def test_nfl_current_injury_report_allows_clear_player_but_not_questionable(monkeypatch):
    collector = LivePlayerFeatureCollector(now=NOW, production_verified=False)
    monkeypatch.setattr(
        collector,
        "_nfl_card_context",
        lambda card: {"home_abbr": "CHI", "away_abbr": "PHI", "week": 4},
    )
    depth = {"team": "PHI", "gsis_id": "00-1"}

    def injury_payload(status):
        return {
            "injuries": [{
                "team": {"abbreviation": "PHI"},
                "injuries": (
                    [] if status == ""
                    else [{
                        "athlete": {"displayName": "Test Runner"},
                        "status": status,
                    }]
                ),
            }]
        }

    monkeypatch.setattr(
        "jabazi.providers.player_features_live._fetch_json",
        lambda url, timeout=20, headers=None: injury_payload(""),
    )
    clear = collector._nfl_injury_evidence(nfl_card(), "Test Runner", depth)
    assert clear["verified"] is True
    assert clear["available_by_injury_report"] is True

    monkeypatch.setattr(
        "jabazi.providers.player_features_live._fetch_json",
        lambda url, timeout=20, headers=None: injury_payload("Questionable"),
    )
    questionable = collector._nfl_injury_evidence(nfl_card(), "Test Runner", depth)
    assert questionable["verified"] is False
    assert questionable["available_by_injury_report"] is False


def test_mlb_posted_batting_order_satisfies_current_injury_gate(monkeypatch):
    collector = LivePlayerFeatureCollector(now=NOW, production_verified=False)
    start = NOW + timedelta(hours=3)
    card = SimpleNamespace(
        sport="baseball_mlb",
        event_id="mlb-test",
        event="New York Yankees @ Boston Red Sox",
        market="batter_hits",
        participant="Test Batter",
        starts_at=start,
        in_play=False,
    )
    logs = []
    for i in range(6):
        date = (NOW.date() - timedelta(days=10 - i)).isoformat()
        logs.append({
            "date": date,
            "game": {"gamePk": 100 + i},
            "stat": {
                "hits": 1,
                "doubles": 0,
                "triples": 0,
                "homeRuns": 0,
                "runs": 1,
                "rbi": 0,
                "baseOnBalls": 0,
                "plateAppearances": 4,
            },
        })
    monkeypatch.setattr(collector, "_mlb_game_logs", lambda participant, group: logs)
    monkeypatch.setattr(collector, "_mlb_projection_for", lambda participant, starts_at: None)
    monkeypatch.setattr(collector, "_mlb_person", lambda participant: {"id": 123})
    monkeypatch.setattr(
        collector,
        "_mlb_official_role",
        lambda card, person, pitcher: {
            "role": 2.0,
            "role_ok": True,
            "active_roster": True,
            "event_identity": True,
            "team": "home",
            "source": "MLB StatsAPI posted battingOrder",
        },
    )
    payload = collector.mlb_snapshot(card)
    assert payload is not None
    assert payload["integrity"]["role"] is True
    assert payload["integrity"]["availability"] is True
    assert payload["integrity"]["injuries"] is True
    assert "SportsDataIO" not in payload["provider"]


def test_mlb_probable_pitcher_plus_active_roster_clears_current_gate(monkeypatch):
    collector = LivePlayerFeatureCollector(now=NOW, production_verified=False)
    start = NOW + timedelta(hours=3)
    card = SimpleNamespace(
        sport="baseball_mlb",
        event_id="mlb-pitcher-test",
        event="New York Yankees @ Boston Red Sox",
        market="pitcher_strikeouts",
        participant="Test Pitcher",
        starts_at=start,
        in_play=False,
    )
    logs = []
    for i in range(6):
        date = (NOW.date() - timedelta(days=10 - i)).isoformat()
        logs.append({
            "date": date,
            "game": {"gamePk": 200 + i},
            "stat": {
                "strikeOuts": 6,
                "inningsPitched": "6.0",
                "hits": 4,
                "baseOnBalls": 2,
                "battersFaced": 24,
            },
        })
    monkeypatch.setattr(collector, "_mlb_game_logs", lambda participant, group: logs)
    monkeypatch.setattr(collector, "_mlb_projection_for", lambda participant, starts_at: None)
    monkeypatch.setattr(collector, "_mlb_person", lambda participant: {"id": 456})
    monkeypatch.setattr(
        collector,
        "_mlb_official_role",
        lambda card, person, pitcher: {
            "role": 1.0,
            "role_ok": True,
            "active_roster": True,
            "event_identity": True,
            "team": "home",
            "source": "MLB StatsAPI probablePitcher",
        },
    )
    payload = collector.mlb_snapshot(card)
    assert payload["integrity"]["availability"] is True
    assert payload["integrity"]["injuries"] is True

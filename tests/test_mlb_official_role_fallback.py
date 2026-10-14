from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jabazi.providers.player_features_live import LivePlayerFeatureCollector


def test_mlb_official_role_fallback_archives_research_probability_inputs(monkeypatch):
    now = datetime(2026, 9, 28, 18, tzinfo=UTC)
    collector = LivePlayerFeatureCollector(now=now, production_verified=False)
    logs = []
    for i in range(6):
        logs.append({
            "date": (now.date() - timedelta(days=10-i)).isoformat(),
            "game": {"gamePk": 100 + i},
            "stat": {
                "hits": 1 + i % 2,
                "doubles": 0,
                "triples": 0,
                "homeRuns": 0,
                "runs": 1,
                "rbi": 1,
                "baseOnBalls": 0,
                "plateAppearances": 4,
            },
        })
    monkeypatch.setattr(collector, "_mlb_game_logs", lambda participant, group: logs)
    monkeypatch.setattr(collector, "_mlb_projection_for", lambda participant, starts_at: None)
    monkeypatch.setattr(collector, "_mlb_person", lambda participant: {"id": 42, "fullName": participant})
    monkeypatch.setattr(
        collector,
        "_mlb_official_role",
        lambda card, person, pitcher: {
            "role": 2.0,
            "role_ok": True,
            "event_identity": True,
            "team": "home",
            "source": "MLB StatsAPI posted battingOrder",
        },
    )
    card = SimpleNamespace(
        sport="baseball_mlb",
        event_id="odds-event",
        event="Away Team @ Home Team",
        market="batter_hits",
        participant="Test Batter",
        starts_at=now + timedelta(hours=4),
    )
    snapshot = collector.mlb_snapshot(card)
    assert snapshot is not None
    assert snapshot["provider"] == "MLB StatsAPI official history+schedule/role"
    assert snapshot["integrity"]["event_identity"] is True
    assert snapshot["integrity"]["role"] is True
    assert snapshot["integrity"]["availability"] is True
    # Posted role is not proof of no injury/late scratch; production stays closed.
    assert snapshot["integrity"]["injuries"] is False
    assert snapshot["expected_opportunities"] == 4

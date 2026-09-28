from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from jabazi.models.player_distribution import (
    COUNT_MARKETS,
    PLAYER_PROP_MARKETS,
    PlayerPropModel,
)
from jabazi.providers import nhl_player_features as nhlp


NOW = datetime(2026, 9, 28, 18, tzinfo=UTC)
START = datetime(2026, 9, 29, 23, tzinfo=UTC)


def card(market, participant):
    return SimpleNamespace(
        sport="icehockey_nhl",
        event_id="nhl-test-1",
        event="Florida Panthers @ Carolina Hurricanes",
        market=market,
        participant=participant,
        in_play=False,
        starts_at=START,
        selection="Over",
        line=2.5,
        observed_at=NOW,
    )


def fake_fetch(url, timeout=12):
    if "/roster/CAR/current" in url:
        return {
            "forwards": [{
                "id": 8478427,
                "firstName": {"default": "Sebastian"},
                "lastName": {"default": "Aho"},
                "positionCode": "C",
            }],
            "defensemen": [],
            "goalies": [],
        }, "car-roster"
    if "/roster/FLA/current" in url:
        return {
            "forwards": [],
            "defensemen": [],
            "goalies": [{
                "id": 8475683,
                "firstName": {"default": "Sergei"},
                "lastName": {"default": "Bobrovsky"},
                "positionCode": "G",
            }],
        }, "fla-roster"
    if "/skater/summary?" in url:
        rows = [
            {
                "playerId": 8478427,
                "gameId": 2025020000 + i,
                "gameDate": f"2026-09-{20+i:02d}",
                "points": i % 3,
                "assists": i % 2,
                "shots": 2 + i % 4,
                "goals": i % 2,
                "timeOnIcePerGame": "19:30",
            }
            for i in range(1, 7)
        ]
        return {"data": rows}, "skater-stats"
    if "/goalie/summary?" in url:
        rows = [
            {
                "playerId": 8475683,
                "gameId": 2025020100 + i,
                "gameDate": f"2026-09-{20+i:02d}",
                "saves": 25 + i,
                "shotsAgainst": 28 + i,
            }
            for i in range(1, 7)
        ]
        return {"data": rows}, "goalie-stats"
    raise AssertionError(url)


def test_nhl_prop_markets_registered_as_count_distributions():
    expected = {
        "player_points",
        "player_power_play_points",
        "player_assists",
        "player_blocked_shots",
        "player_shots_on_goal",
        "player_goals",
        "player_total_saves",
    }
    assert expected <= PLAYER_PROP_MARKETS["icehockey_nhl"]
    assert expected <= COUNT_MARKETS


def test_official_skater_history_builds_research_only_snapshot(monkeypatch):
    monkeypatch.setattr(nhlp, "_fetch_json", fake_fetch)
    collector = nhlp.NHLPlayerFeatureCollector(now=NOW)
    snapshot = collector.snapshot(card("player_shots_on_goal", "Sebastian Aho"))
    assert snapshot is not None
    assert snapshot["player_id"] == "8478427"
    assert snapshot["provider"] == "NHL official roster+stats"
    assert snapshot["features"]["position_forward"] == 1
    assert snapshot["features"]["position_goalie"] == 0
    assert snapshot["integrity"]["event_identity"] is True
    assert snapshot["integrity"]["role"] is True
    # Official historical stats and roster membership do not establish same-day health.
    assert snapshot["integrity"]["injuries"] is False


def test_goalie_history_never_claims_starting_role(monkeypatch):
    monkeypatch.setattr(nhlp, "_fetch_json", fake_fetch)
    collector = nhlp.NHLPlayerFeatureCollector(now=NOW)
    c = card("player_total_saves", "Sergei Bobrovsky")
    c.line = 27.5
    snapshot = collector.snapshot(c)
    assert snapshot is not None
    assert snapshot["features"]["position_goalie"] == 1
    assert snapshot["integrity"]["role"] is False
    assert snapshot["integrity"]["injuries"] is False


@pytest.mark.parametrize("market", ["player_power_play_points", "player_blocked_shots"])
def test_unvalidated_secondary_nhl_markets_do_not_create_live_features(monkeypatch, market):
    monkeypatch.setattr(nhlp, "_fetch_json", fake_fetch)
    collector = nhlp.NHLPlayerFeatureCollector(now=NOW)
    assert collector.snapshot(card(market, "Sebastian Aho")) is None


def test_nhl_count_artifact_can_infer_but_cannot_self_approve():
    features = nhlp.rolling_features(
        [2, 3, 4, 2, 5, 3],
        [18, 19, 20, 19, 21, 20],
        is_home=True,
        position="C",
    )
    names = sorted(features)
    artifact = {
        "artifact_type": "player_prop_distribution",
        "artifact_schema_version": 3,
        "sport": "icehockey_nhl",
        "market": "player_shots_on_goal",
        "provider": "NHL official stats",
        "feature_names": names,
        "scaler": {"mean": [0.0] * len(names), "scale": [1.0] * len(names)},
        "family": "count_nb",
        "parameters": {
            "coef": [0.0] * len(names),
            "intercept": 1.1,
            "dispersion": 0.15,
        },
        "model_version": "nhl-player_shots_on_goal-dist-test",
        "stage": "SHADOW_ONLY",
        "validation": {"promotion_passed": False, "prospective_sample_count": 0},
    }
    payload = {
        "sport": "icehockey_nhl",
        "event_id": "nhl-test-1",
        "participant": "Sebastian Aho",
        "market": "player_shots_on_goal",
        "features": features,
        "features_available_at": NOW.isoformat(),
        "starts_at": START.isoformat(),
        "research_only": True,
        "production_inputs_verified": False,
        "integrity": {
            "event_identity": True,
            "player_identity": True,
            "fresh_features": True,
            "schema": True,
            "role": True,
            "availability": True,
            "injuries": False,
            "no_duplicate_event": True,
        },
    }

    class Store:
        def list_records(self, kind, limit, entity=None):
            assert kind == "player_feature_snapshot"
            return [{"payload": payload}]

    model = PlayerPropModel(artifact, Store())
    p = card("player_shots_on_goal", "Sebastian Aho")
    estimate = model.estimate(p)
    assert estimate is not None
    assert 0 < float(estimate.probability) < 1
    assert estimate.approved_for_betting is False
    assert estimate.feature_snapshot["production_inputs_verified"] is False

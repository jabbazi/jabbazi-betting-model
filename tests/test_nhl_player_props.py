from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from jabazi.models.player_distribution import (
    COUNT_MARKETS,
    PLAYER_PROP_MARKETS,
    PlayerPropModel,
)
from jabazi.providers import nhl_player_features as nhlp


NOW = datetime.now(UTC)
START = NOW + timedelta(days=1)


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
    if "site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries" in url:
        return {
            "injuries": [
                {"team": {"abbreviation": "CAR"}, "injuries": []},
                {"team": {"abbreviation": "FLA"}, "injuries": []},
            ]
        }, "espn-injuries"
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
                "timeOnIcePerGame": 1170,
            }
            for i in range(1, 7)
        ]
        return {"data": rows}, "skater-stats"
    if "scoreboard?dates=" in url:
        return {
            "events": [{
                "id": "nhl-test-event",
                "competitions": [{
                    "competitors": [
                        {"team": {"displayName": "Florida Panthers"}},
                        {"team": {"displayName": "Carolina Hurricanes"}},
                    ]
                }],
            }]
        }, "espn-scoreboard"
    if "summary?event=nhl-test-event" in url:
        return {
            "boxscore": {
                "players": [{
                    "statistics": [{
                        "athletes": [{
                            "starter": False,
                            "athlete": {"displayName": "Sergei Bobrovsky"},
                        }]
                    }]
                }]
            }
        }, "espn-summary"
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
    assert snapshot["provider"] == "NHL official roster+stats + ESPN injury cross-check"
    assert snapshot["features"]["position_forward"] == 1
    assert snapshot["features"]["position_goalie"] == 0
    assert snapshot["integrity"]["event_identity"] is True
    assert snapshot["integrity"]["role"] is True
    assert snapshot["integrity"]["injuries"] is True
    assert snapshot["integrity"]["availability"] is True


def test_goalie_history_never_claims_starting_role(monkeypatch):
    monkeypatch.setattr(nhlp, "_fetch_json", fake_fetch)
    collector = nhlp.NHLPlayerFeatureCollector(now=NOW)
    c = card("player_total_saves", "Sergei Bobrovsky")
    c.line = 27.5
    snapshot = collector.snapshot(c)
    assert snapshot is not None
    assert snapshot["features"]["position_goalie"] == 1
    assert snapshot["integrity"]["role"] is False
    assert snapshot["integrity"]["injuries"] is True
    assert snapshot["integrity"]["availability"] is True


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
    assert estimate.feature_snapshot["integrity"]["variance"] is True
    assert estimate.feature_snapshot["integrity"]["starter"] is True
    assert estimate.feature_snapshot["integrity"]["roster"] is True
    assert estimate.feature_snapshot["integrity"]["calibration"] is False


def test_historical_dataset_uses_only_lagged_prior_results():
    from jabazi.research.nhl_player_experiment import build_dataset

    base = datetime(2025, 1, 1, 23, tzinfo=UTC)
    games = []
    stats = []
    for i in range(8):
        start = base + timedelta(days=3 * i)
        gid = str(2025020001 + i)
        games.append({
            "game_id": gid,
            "completed": True,
            "starts_at": start.isoformat(),
            "available_at": (start + timedelta(hours=48)).isoformat(),
            "home_team": "Carolina Hurricanes",
            "away_team": "Florida Panthers",
        })
        stats.append({
            "playerId": 8478427,
            "gameId": int(gid),
            "gameDate": start.date().isoformat(),
            "teamAbbrevs": "CAR",
            "skaterFullName": "Sebastian Aho",
            "positionCode": "C",
            "shots": i,
            "points": i % 3,
            "assists": i % 2,
            "goals": i % 2,
            "timeOnIcePerGame": 1140,
        })

    document = build_dataset(
        games=games,
        skater_rows=stats,
        goalie_rows=[],
        market="player_shots_on_goal",
        source_checksum="source-test",
        research_rights_reference="test fixture only",
    )
    assert len(document["rows"]) == 3
    first = document["rows"][0]
    # Game six can only use games one through five; its own six-shot outcome
    # cannot enter the feature vector.
    assert first["observed_value"] == 5
    assert first["features"]["last1_value"] == 4
    assert first["features"]["games_prior"] == 5
    assert first["features_available_at"] < first["prediction_at"] < first["starts_at"]
    assert first["market_no_vig_probability"] is None
    assert document["manifest"]["market_prices_included"] is False


def test_registered_nhl_artifacts_are_validating_not_approved():
    from jabazi.models.player_registry import load_player_models, player_status

    models, errors = load_player_models()
    assert not [error for error in errors if error.startswith("icehockey_nhl:")]
    status = player_status(models, "icehockey_nhl")
    assert status["status"] == "VALIDATING"
    assert status["approved_for_betting"] is False
    assert {
        "player_assists",
        "player_goals",
        "player_points",
        "player_shots_on_goal",
        "player_total_saves",
    } <= set(status["supported_markets"])


def test_nhl_injury_crosscheck_keeps_ambiguous_player_fail_closed(monkeypatch):
    def injured_fetch(url, timeout=12):
        if "site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries" in url:
            return {
                "injuries": [{
                    "team": {"abbreviation": "CAR"},
                    "injuries": [{
                        "athlete": {"displayName": "Sebastian Aho"},
                        "status": "Day-To-Day",
                    }],
                }]
            }, "injury-checksum"
        return fake_fetch(url, timeout)

    monkeypatch.setattr(nhlp, "_fetch_json", injured_fetch)
    collector = nhlp.NHLPlayerFeatureCollector(now=NOW)
    snapshot = collector.snapshot(card("player_shots_on_goal", "Sebastian Aho"))
    assert snapshot is not None
    assert snapshot["integrity"]["availability"] is False
    assert snapshot["integrity"]["injuries"] is False

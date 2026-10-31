"""Isolated regression tests for NBA/NHL prospective evidence capture.

Synthetic fixtures only. Passing tests do not establish authentic source
provenance, prospective calibration, or wagering approval.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from jabazi.models.player_distribution import PlayerPropModel
from jabazi.persistence.store import Store
from jabazi.research.player_features import REQUIRED_INTEGRITY
from jabazi.research.player_prospective import freeze_player_candidate, validation_report


NOW = datetime.now(UTC)
START = NOW + timedelta(hours=3)


@pytest.fixture
def store():
    value = Store("sqlite:///:memory:", initialize=True)
    yield value
    value.close()


def price(sport, market):
    return SimpleNamespace(
        sport=sport, event_id="fixture-event", participant="Fixture Athlete",
        market=market, selection="over", line=Decimal("20.5"),
        in_play=False, starts_at=START,
        observed_at=NOW - timedelta(seconds=15),
        source_timestamp=NOW - timedelta(seconds=15),
        consensus_probability=Decimal(".5"),
        quote_ids=("fixture-quote",), best_book="fixture-book",
        best_decimal=Decimal("1.9"),
    )


def estimate(verified=True):
    return SimpleNamespace(
        probability=Decimal(".57"), model_version="fixture-model-v1",
        approved_for_betting=False,
        feature_snapshot={
            "event_id": "fixture-event", "participant": "Fixture Athlete",
            "features_available_at": (NOW - timedelta(minutes=10)).isoformat(),
            "snapshot_id": "playerfs-" + "a" * 20,
            "research_only": not verified,
            "production_inputs_verified": verified,
            "provider": "ESPN",
            "integrity": {key: True for key in REQUIRED_INTEGRITY},
        },
    )


@pytest.mark.parametrize("sport,market", [
    ("basketball_nba", "player_points"),
    ("basketball_nba", "player_assists"),
    ("icehockey_nhl", "player_shots_on_goal"),
    ("icehockey_nhl", "player_total_saves"),
    ("americanfootball_nfl", "player_receptions"),
])
def test_player_markets_freeze_without_wagering_approval(store, sport, market):
    card = price(sport, market)
    assert freeze_player_candidate(store, card, estimate(), {}, now=NOW)
    assert freeze_player_candidate(store, card, estimate(), {}, now=NOW) is False
    report = validation_report(store)
    assert report["buckets"][0]["frozen"] == 1
    assert report["buckets"][0]["pending"] == 1
    assert report["buckets"][0]["data_health_failures"] == 0


def test_unverified_nhl_snapshot_is_not_trusted_for_calibration(store):
    card = price("icehockey_nhl", "player_shots_on_goal")
    assert freeze_player_candidate(store, card, estimate(verified=False), {}, now=NOW)
    bucket = validation_report(store)["buckets"][0]
    assert bucket["sample_count"] == 0
    assert bucket["data_health_failures"] == 1


def test_wrong_sport_market_is_not_recorded(store):
    assert not freeze_player_candidate(
        store, price("icehockey_nhl", "player_points_rebounds"),
        estimate(), {}, now=NOW,
    )


def test_validating_nba_artifact_preserves_verified_inputs_without_approval():
    artifact = json.loads(
        (Path(__file__).resolve().parents[1]
         / "models/player_props/basketball_nba/player_points.json").read_text()
    )
    assert artifact["stage"] == "VALIDATING"
    features = dict(zip(artifact["feature_names"], artifact["scaler"]["mean"]))
    snapshot = {
        "sport": "basketball_nba", "event_id": "fixture-event",
        "participant": "Fixture Athlete", "market": "player_points",
        "features": features, "starts_at": START.isoformat(),
        "features_available_at": (NOW - timedelta(minutes=10)).isoformat(),
        "research_only": False, "production_inputs_verified": True,
        "provider": "ESPN",
        "integrity": {key: True for key in REQUIRED_INTEGRITY},
    }

    class FakeStore:
        def list_records(self, kind, limit, entity=None):
            return [{"payload": snapshot}]

    result = PlayerPropModel(artifact, FakeStore()).estimate(
        price("basketball_nba", "player_points")
    )
    assert result is not None
    assert 0 < result.probability < 1
    assert result.approved_for_betting is False
    assert result.feature_snapshot["production_inputs_verified"] is True


def test_unverified_nba_artifact_remains_unapproved():
    artifact = json.loads(
        (Path(__file__).resolve().parents[1]
         / "models/player_props/basketball_nba/player_points.json").read_text()
    )
    features = dict(zip(artifact["feature_names"], artifact["scaler"]["mean"]))
    snapshot = {
        "sport": "basketball_nba", "event_id": "fixture-event",
        "participant": "Fixture Athlete", "market": "player_points",
        "features": features, "starts_at": START.isoformat(),
        "features_available_at": (NOW - timedelta(minutes=10)).isoformat(),
        "research_only": True, "production_inputs_verified": False,
        "provider": "ESPN",
        "integrity": {key: True for key in REQUIRED_INTEGRITY},
    }

    class FakeStore:
        def list_records(self, kind, limit, entity=None):
            return [{"payload": snapshot}]

    result = PlayerPropModel(artifact, FakeStore()).estimate(
        price("basketball_nba", "player_points")
    )
    assert result is not None
    assert result.approved_for_betting is False
    assert result.feature_snapshot["production_inputs_verified"] is False

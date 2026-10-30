"""Prospective evidence must accumulate before model wagering promotion.

These are synthetic regression fixtures, never live calibration evidence.
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
from jabazi.research.player_prospective import (
    archive_player_result, freeze_player_candidate, validation_report,
)

NOW = datetime.now(UTC)
START = NOW + timedelta(hours=2)


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
        observed_at=NOW - timedelta(seconds=30),
        source_timestamp=NOW - timedelta(seconds=30),
        consensus_probability=Decimal(".50"),
        quote_ids=("fixture-quote",), best_book="fixture-book",
        best_decimal=Decimal("1.90"),
    )


def estimate():
    return SimpleNamespace(
        probability=Decimal(".57"), model_version="fixture-model-v1",
        approved_for_betting=False,
        feature_snapshot={
            "event_id": "fixture-event", "participant": "Fixture Athlete",
            "features_available_at": (NOW - timedelta(minutes=10)).isoformat(),
            "snapshot_id": "playerfs-" + "a" * 20,
            "research_only": False, "production_inputs_verified": True,
            "provider": "verified-source",
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
def test_all_sport_player_markets_can_freeze_before_approval(store, sport, market):
    card = price(sport, market)
    result = freeze_player_candidate(store, card, estimate(), {}, now=NOW)
    assert result
    # Frozen research predictions are not wagers or approvals.
    assert freeze_player_candidate(store, card, estimate(), {}, now=NOW) is False
    report = validation_report(store)
    assert report["buckets"][0]["frozen"] == 1
    assert report["buckets"][0]["pending"] == 1
    assert report["buckets"][0]["data_health_failures"] == 0


def test_nba_frozen_research_can_be_evaluated_after_final_result(store, monkeypatch):
    from jabazi.research import player_prospective as module
    card = price("basketball_nba", "player_points")
    assert freeze_player_candidate(store, card, estimate(), {}, now=NOW)
    # Simulate time advancing past the final game; do not create future
    # settlement evidence relative to the simulated observation clock.
    class AfterFinalClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = START + timedelta(hours=4)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    monkeypatch.setattr(module, "datetime", AfterFinalClock)
    assert archive_player_result(
        store, sport=card.sport, event_id=card.event_id,
        participant=card.participant, market=card.market,
        observed_value=24, starts_at=START.isoformat(),
        observed_at=START + timedelta(hours=3),
        source_checksum="fixture-final-stat-checksum",
    )
    bucket = validation_report(store)["buckets"][0]
    assert bucket["sample_count"] == 1
    assert bucket["independent_event_count"] == 1
    assert bucket["data_health_failures"] == 0
    assert bucket["brier"] is not None


def test_unverified_feature_inputs_never_become_trusted_prospective_samples(store):
    card = price("basketball_nba", "player_points")
    model = estimate()
    model.feature_snapshot["production_inputs_verified"] = False
    assert freeze_player_candidate(store, card, model, {}, now=NOW)
    bucket = validation_report(store)["buckets"][0]
    assert bucket["sample_count"] == 0
    assert bucket["data_health_failures"] == 1


def test_validating_model_retains_verified_inputs_without_wagering_approval():
    path = (Path(__file__).resolve().parents[1] /
            "models/player_props/basketball_nba/player_points.json")
    artifact = json.loads(path.read_text())
    assert artifact["stage"] == "VALIDATING"
    features = dict(zip(artifact["feature_names"], artifact["scaler"]["mean"]))
    snapshot = {
        "sport": "basketball_nba", "event_id": "fixture-event",
        "participant": "Fixture Athlete", "market": "player_points",
        "features": features, "starts_at": START.isoformat(),
        "features_available_at": (NOW - timedelta(minutes=10)).isoformat(),
        "research_only": False, "production_inputs_verified": True,
        "provider": "ESPN", "integrity": {key: True for key in REQUIRED_INTEGRITY},
    }
    class FakeStore:
        def list_records(self, kind, limit, entity=None):
            return [{"payload": snapshot}]
    model = PlayerPropModel(artifact, FakeStore())
    result = model.estimate(price("basketball_nba", "player_points"))
    assert result is not None
    assert 0 < result.probability < 1
    assert result.approved_for_betting is False
    assert result.feature_snapshot["production_inputs_verified"] is True


def test_future_dated_player_result_cannot_be_archived(store):
    with pytest.raises(ValueError, match="Future player result"):
        archive_player_result(
            store, sport="basketball_nba", event_id="fixture-event",
            participant="Fixture Athlete", market="player_points",
            observed_value=24, starts_at=START.isoformat(),
            observed_at=START + timedelta(hours=3),
            source_checksum="fixture-only",
        )

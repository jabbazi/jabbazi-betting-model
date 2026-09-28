from copy import deepcopy

import pytest

from jabazi.persistence.store import Store
from jabazi.research.player_features import REQUIRED_INTEGRITY
from jabazi.research.player_prospective import validation_report, _event_comparison
from jabazi.research.player_model_refresh import refresh_promotions


@pytest.fixture
def store():
    value = Store("sqlite:///:memory:", initialize=True)
    yield value
    value.close()


def forecast(line=50.5, side="over"):
    return dict(
        sport="americanfootball_nfl", event_id="game-1", participant="Player",
        model_version="v1", market="player_reception_yds", selection=side, line=line,
        starts_at="2026-09-27T20:00:00+00:00", predicted_at="2026-09-27T19:00:00+00:00",
        probability=.6, market_probability=.5,
        feature_snapshot=dict(
            research_only=False, production_inputs_verified=True, provider="verified-source",
            settlement_rules="full-game-including-ot-dnp-void",
            integrity={k: True for k in REQUIRED_INTEGRITY},
        ),
    )


def result(f):
    return {k: f[k] for k in ("sport", "event_id", "participant", "market", "starts_at")} | {
        "observed_value": 80, "result_status": "final",
        "closing_no_vig_probability": .7,
    }


def seed(store, f, r):
    store.append("player_prospective_forecast", f["event_id"], f)
    store.append("player_prospective_result", f["event_id"], r)


def test_alternate_ladder_is_not_independent_events(store):
    for line in (40.5, 50.5, 60.5):
        f = forecast(line)
        seed(store, f, result(f))
    bucket = validation_report(store)["buckets"][0]
    assert bucket["sample_count"] == 3
    assert bucket["independent_event_count"] == 1
    assert bucket["clv_sample_count"] == 0  # Legacy unbound closing probability.
    assert bucket["event_weighted_market_comparison"]["interval_95"] is None


def test_clustered_comparison_weights_games_not_number_of_props():
    values = {"a": [-.1] * 100, "b": [.2]}
    report = _event_comparison(values)
    assert report["independent_events"] == 2
    assert report["brier_difference"] == pytest.approx(.05)
    assert report == _event_comparison(values)
    assert report["interval_95"][0] < 0 < report["interval_95"][1]
    assert _event_comparison({})["brier_difference"] is None


@pytest.mark.parametrize("change", [
    {"research_only": True}, {"production_inputs_verified": False},
    {"provider": "SportsDataIO", "provider_data_verified": False},
    {"integrity": {}},
])
def test_unverified_forecasts_never_enter_promotion_metrics(store, change):
    f = forecast()
    f["feature_snapshot"].update(change)
    seed(store, f, result(f))
    bucket = validation_report(store)["buckets"][0]
    assert bucket["data_health_failures"] == 1
    assert bucket["sample_count"] == 0
    assert bucket["brier"] is None


@pytest.mark.parametrize("change,expected", [
    ({}, 1), ({"selection": "under"}, 0), ({"line": 60.5}, 0),
    ({"event_id": "other"}, 0), ({"settlement_rules": "regulation"}, 0),
    ({"observed_at": "2026-09-27T20:01:00+00:00"}, 0),
    ({"source_checksum": ""}, 0),
])
def test_clv_requires_exact_market_and_pregame_receipt(store, change, expected):
    f = forecast()
    r = result(f)
    r["closing_quote"] = {k: f[k] for k in (
        "sport", "event_id", "participant", "market", "selection", "line"
    )} | dict(
        settlement_rules=f["feature_snapshot"]["settlement_rules"],
        observed_at="2026-09-27T19:59:00+00:00", source_checksum="receipt",
        no_vig_probability=.55,
    ) | change
    seed(store, f, r)
    bucket = validation_report(store)["buckets"][0]
    assert bucket["clv_sample_count"] == expected
    assert bucket["clv_independent_event_count"] == expected
    if expected:
        assert bucket["mean_clv_prob_points"] == pytest.approx(5)


def test_refresh_updates_only_current_artifact_and_changed_evidence(store, monkeypatch):
    import jabazi.research.player_model_refresh as module

    f = forecast()
    evidence = dict(sample_count=800, independent_event_count=800, identity_failures=0,
                    brier=.2, market_baseline_brier=.23, ece=.02, clv_sample_count=250,
                    clv_independent_event_count=250, mean_clv_prob_points=.5,
                    data_health_failures=0, sport=f["sport"], market=f["market"], model_version="new")
    monkeypatch.setattr(module, "validation_report", lambda s: {"buckets": [deepcopy(evidence)]})
    for version in ("old", "new"):
        store.append("player_prop_model", "model", dict(
            sport=f["sport"], market=f["market"], model_version=version,
            stage="VALIDATING", distribution_validation={"n": 1000}, validation={},
        ))
    changes = refresh_promotions(store)
    assert len(changes) == 1 and changes[0]["model_version"] == "new"
    assert changes[0]["stage"] == "PRODUCTION_APPROVED"
    assert refresh_promotions(store) == []
    # Same n and stage, changed performance must still update the evidence.
    evidence["brier"] = .21
    assert len(refresh_promotions(store)) == 1
    evidence["identity_failures"] = 1
    assert refresh_promotions(store)[0]["stage"] == "VALIDATING"
    evidence["identity_failures"] = 0
    assert refresh_promotions(store)[0]["stage"] == "PRODUCTION_APPROVED"

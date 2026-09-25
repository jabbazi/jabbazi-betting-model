from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from jabazi.persistence.store import Store
from jabazi.research.prospective import (
    archive_results,
    freeze_candidate,
    outcome,
    validation_report,
)

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
SPORT = "americanfootball_nfl"


@pytest.fixture
def store():
    s = Store("sqlite:///:memory:", initialize=True)
    yield s
    s.close()


def inputs(market="h2h", line=None):
    c = SimpleNamespace(
        sport=SPORT,
        event_id="odds-1",
        market=market,
        selection="Home",
        participant=None,
        line=line,
        starts_at=NOW + timedelta(hours=1),
        observed_at=NOW,
        source_timestamp=NOW,
        consensus_probability=Decimal("0.6"),
        quote_ids=("q1", "q2"),
        best_book="test",
        best_decimal=Decimal("1.8"),
    )
    if "total" in market:
        c.selection = "Over"
        c.participant = "Home" if "team" in market else None
    e = SimpleNamespace(
        probability=Decimal("0.7"),
        model_version="nfl-test-v1",
        feature_snapshot={
            "schedule_game_id": "schedule-1",
            "feature_schema_version": "v1",
            "dataset_hash": "hash",
            "code_commit": "commit",
            "state_refreshed_at": NOW.isoformat(),
            "home_team": "Home",
            "away_team": "Away",
            "push_probability": 0,
            "production_inputs_verified": False,
        },
    )
    return c, e


def result(h=24, a=17):
    return dict(
        game_id="schedule-1",
        starts_at=(NOW + timedelta(hours=1)).isoformat(),
        home_team="Home",
        away_team="Away",
        home_score=h,
        away_score=a,
        season=2026,
        neutral_site=False,
    )


def archive(s, g):
    return archive_results(
        s, SPORT, [g], observed_at=NOW + timedelta(days=2), source_checksum="receipt"
    )


def test_first_forecast_is_immutable_and_duplicate_ladders_do_not_inflate(store):
    c, e = inputs("alternate_spreads", Decimal("3.5"))
    assert freeze_candidate(store, c, e, {}, now=NOW)
    c.line = Decimal("14.5")
    e.probability = Decimal("0.99")
    c.event_id = "duplicate-provider-id"
    assert not freeze_candidate(store, c, e, {}, now=NOW)
    rows = store.list_records("prospective_forecast")
    assert len(rows) == 1 and rows[0]["payload"]["probability"] == 0.7
    assert archive(store, result()) == 1
    assert archive(store, result()) == 0
    b = validation_report(store)["buckets"][0]
    assert b["model"]["n"] == 1 and b["model"]["brier"] == pytest.approx(0.09)
    assert b["market"]["brier"] == pytest.approx(0.16)
    assert b["input_verified"] == 0 and not b["approved_for_betting"]


@pytest.mark.parametrize(
    "failure",
    [
        "live",
        "stale",
        "future_quote",
        "missing_commit",
        "away",
        "future_features",
        "push",
    ],
)
def test_ineligible_freezes_are_excluded(store, failure):
    c, e = inputs("spreads", Decimal("3.5"))
    if failure == "live":
        c.starts_at = NOW
    if failure == "stale":
        c.source_timestamp = NOW - timedelta(seconds=121)
    if failure == "future_quote":
        c.source_timestamp = NOW + timedelta(seconds=1)
    if failure == "missing_commit":
        e.feature_snapshot["code_commit"] = None
    if failure == "away":
        c.selection = "Away"
    if failure == "future_features":
        e.feature_snapshot["state_refreshed_at"] = (
            NOW + timedelta(seconds=1)
        ).isoformat()
    if failure == "push":
        e.feature_snapshot["push_probability"] = 0.1
    assert not freeze_candidate(store, c, e, {}, now=NOW)


@pytest.mark.parametrize(
    "market,line,expected",
    [
        ("h2h", None, "WIN"),
        ("spreads", -7, "PUSH"),
        ("alternate_spreads", -7.5, "LOSS"),
        ("totals", 40.5, "WIN"),
        ("alternate_totals", 41.5, "LOSS"),
        ("team_totals", 23.5, "WIN"),
        ("alternate_team_totals", 24.5, "LOSS"),
    ],
)
def test_market_orientation(store, market, line, expected):
    c, e = inputs(market, line)
    assert freeze_candidate(store, c, e, {}, now=NOW)
    f = store.list_records("prospective_forecast")[0]["payload"]
    assert outcome(f, result() | {"sport": SPORT}) == expected


def test_ties_and_result_corrections_preserve_evidence(store):
    c, e = inputs()
    freeze_candidate(store, c, e, {}, now=NOW)
    assert validation_report(store)["buckets"][0]["pending"] == 1
    archive(store, result(17, 17))
    b = validation_report(store)["buckets"][0]
    assert b["pushes"] == 1 and b["model"]["n"] == 0
    archive(store, result(17, 20))
    assert len(store.list_records("prospective_result")) == 2
    b = validation_report(store)["buckets"][0]
    assert b["model"]["brier"] == pytest.approx(0.49)
    assert b["model"]["n"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("home_team", "Away"),
        ("game_id", "wrong"),
        ("starts_at", (NOW + timedelta(days=1)).isoformat()),
        ("home_score", -1),
    ],
)
def test_result_identity_rejected(store, field, value):
    c, e = inputs()
    freeze_candidate(store, c, e, {}, now=NOW)
    f = store.list_records("prospective_forecast")[0]["payload"]
    with pytest.raises(ValueError):
        outcome(f, result() | {"sport": SPORT, field: value})


@pytest.mark.parametrize("short", ["nfl", "mlb", "cfb"])
def test_real_model_to_frozen_evidence_to_status(store, monkeypatch, short):
    from test_score_models import artifact, card
    from jabazi.models.score_distribution import ScoreDistributionModel
    from jabazi.reliability.layer import evaluate, status_buckets

    monkeypatch.setenv("RENDER_GIT_COMMIT", "verified-test-commit")
    model = ScoreDistributionModel(artifact(short))
    price = card(model.artifact)
    estimate = model.estimate(price)
    assert estimate is not None
    assert freeze_candidate(
        store, price, estimate, evaluate(price, estimate, model), now=price.observed_at
    )
    report = validation_report(store)
    assert status_buckets(model, report)["moneyline"]["frozen_prediction_count"] == 1
    f = store.list_records("prospective_forecast")[0]["payload"]
    game = dict(
        game_id=f["schedule_game_id"],
        home_team=f["home_team"],
        away_team=f["away_team"],
        starts_at=f["starts_at"],
        season=price.starts_at.year,
        neutral_site=False,
        home_score=24,
        away_score=17,
    )
    archive_results(
        store,
        model.sport,
        [game],
        observed_at=price.starts_at + timedelta(days=2),
        source_checksum="test-only-result",
    )
    report = validation_report(store)
    b = status_buckets(model, report)["moneyline"]
    assert b["prospective_sample_count"] == 1 and b["pending_result_count"] == 0
    assert b["stage"] == "SHADOW_ONLY" and not b["approved_for_betting"]
    calibration = report["buckets"][0]["calibration"]
    assert calibration[0]["n"] == 1
    assert calibration[0]["wilson_95_low"] < 0.21
    assert calibration[0]["wilson_95_high"] == 1


def test_validation_endpoint_requires_owner_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from jabazi.api import app

    token = "prospective-test-token-at-least-32-characters"
    url = "sqlite:///" + str(tmp_path / "evidence.db")
    Store(url, initialize=True).close()
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", token)
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    with TestClient(app) as client:
        assert client.get("/v1/research/prospective-validation").status_code == 401
        response = client.get(
            "/v1/research/prospective-validation",
            headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code == 200
        assert response.json()["buckets"] == []

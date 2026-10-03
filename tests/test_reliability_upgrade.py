from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
import pytest
from jabazi.models.game_distribution import GameDistribution, ModelHealthError
from jabazi.models.score_distribution import features, score_samples
from jabazi.models.team_elo import timestamp
from jabazi.domain.shopping import build_price_cards
from jabazi.reliability.layer import anomaly
from jabazi.reliability.v42 import ModelStage, ValidationMetrics, evaluate_promotion
from test_shopping import q, NOW


def test_exact_chiefs_miami_regression():
    from tools.diagnose_miami import diagnose

    d = diagnose()
    assert d["status"] == "MODEL_QUARANTINE"
    assert d["score_distribution"]["expected_margin"] == pytest.approx(0.23508771929824562)
    assert d["spread_probabilities"]["10.5"] == 232 / 285
    a = anomaly(d["spread_probabilities"]["10.5"], 0.494764397905759, {})
    assert a["state"] == "EXTREME_DISAGREEMENT" and not a["eligible"]


@pytest.mark.parametrize("sport", ["nfl", "mlb"])
def test_full_distribution_ladders_and_team_total_identity(sport):
    a = json.loads(Path(f"src/jabazi/models/artifacts/{sport}_scores.json").read_text())
    e = a["events"][0]
    v = features(
        a["team_state"],
        e["home_team"],
        e["away_team"],
        timestamp(e["starts_at"]),
        e["neutral_site"],
        a["minimum_games"],
    )
    d = GameDistribution(tuple(score_samples(a, v)))
    assert d.validate_ladders(e["home_team"], e["away_team"])
    s = d.summary()
    assert s["expected_total"] == pytest.approx(
        s["expected_home_points"] + s["expected_away_points"]
    )
    assert s["total_variance"] == pytest.approx(
        s["home_variance"] + s["away_variance"] + 2 * s["score_covariance"]
    )
    for team in (e["home_team"], e["away_team"]):
        previous = 1.0
        for line in [x / 2 for x in range(100)]:
            p = d.outcome("team_totals", "Over", line, e["home_team"], e["away_team"], team)
            u = d.outcome("team_totals", "Under", line, e["home_team"], e["away_team"], team)
            assert p["win"] <= previous and p["win"] + u["win"] + p["push"] == pytest.approx(1)
            previous = p["win"]


def test_toronto_baltimore_opposite_alternate_orientations_are_separate():
    quotes = []
    for book, tor_line, tor_price, bal_price in [
        ("fanduel", "1.5", "1.5552", "2.8"),
        ("draftkings", "-1.5", "2.8", "1.5552"),
    ]:
        for team, line, price in [
            ("Toronto Blue Jays", D(tor_line), tor_price),
            ("Baltimore Orioles", -D(tor_line), bal_price),
        ]:
            quotes.append(
                replace(
                    q(f"{book}:{team}", book, team, price, str(line), "alternate_spreads"),
                    event_name="Toronto Blue Jays @ Baltimore Orioles",
                    sport="baseball_mlb",
                )
            )
    cards = build_price_cards(tuple(quotes), now=NOW)
    assert len(cards) == 4
    pair = [c for c in cards if (c.selection == "Toronto Blue Jays") == (c.line > 0)]
    assert sum(c.consensus_probability for c in pair) == pytest.approx(D(1))
    assert min(c.consensus_probability for c in cards) > D(".35")


def test_no_sgp_independence_shortcut():
    d = GameDistribution(tuple([(30, 10)] * 60 + [(10, 20)] * 40))
    legs = [
        dict(event_id="g", market="h2h", selection="H"),
        dict(event_id="g", market="totals", selection="Over", line=35.5),
    ]
    r = d.joint(legs, home="H", away="A", event_id="g")
    assert r["joint_probability"] == 0.6 and r["joint_probability"] != 0.6 * 0.6
    with pytest.raises(ModelHealthError):
        d.joint(
            [legs[0], dict(legs[1], market="player_passing_yards")],
            home="H",
            away="A",
            event_id="g",
        )


def test_failed_gates_demote_and_retroactive_metrics_cannot_promote():
    good = ValidationMetrics(2000, 0.22, 0.64, 1.0, 0.0, 0.5, 0.1, 0.23)
    assert evaluate_promotion(good).stage == ModelStage.SHADOW_ONLY
    valid = replace(
        good, frozen_prospective=True, model_version="v", market_bucket="NFL:ML", stable_windows=3
    )
    assert evaluate_promotion(valid).stage == ModelStage.PRODUCTION_APPROVED
    assert evaluate_promotion(replace(valid, brier=0.30)).stage == ModelStage.VALIDATING


def test_large_gap_can_clear_checks_but_does_not_auto_promote():
    checks = {
        x: True
        for x in (
            "event_identity",
            "line_identity",
            "fresh_features",
            "schema",
            "variance",
            "pairing",
            "no_duplicate_event",
            "starter",
            "injuries",
            "roster",
            "calibration",
        )
    }
    r = anomaly(0.81, 0.49, checks)
    assert r["state"] == "EXTREME_DISAGREEMENT" and r["eligible"]


def test_cfb_real_trained_artifact_is_registered_shadow_only_and_has_no_props():
    from jabazi.models.registry import load_models
    from test_score_models import card

    models, errors = load_models()
    model = models["americanfootball_ncaaf"]
    assert model.artifact["model_version"].startswith("cfb-recency-ridge-0.2.0-")
    assert all("player" not in m for m in model.supported_markets)
    price = card(model.artifact)
    estimate = model.estimate(price)
    assert estimate is not None and not estimate.approved_for_betting
    assert estimate.feature_snapshot["feature_schema_version"] == "recency-opponent-form-v2"
    assert model.estimate(replace(price, market="player_passing_yards")) is None


def test_status_buckets_visible_through_existing_get_model_status(tmp_path, monkeypatch):
    from jabazi.api import app
    from fastapi.testclient import TestClient
    from jabazi.persistence.store import Store
    from jabazi.chatgpt_api import scanner_key

    db = "sqlite:///" + str(tmp_path / "models.db")
    s = Store(db, initialize=True)
    s.close()
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "test-service-token-for-validation-only-0123456789")
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", db)
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    with TestClient(app) as client:
        result = client.get(
            "/v1/chatgpt/model-status", headers={"Authorization": "Bearer " + scanner_key()}
        )
    assert result.status_code == 200
    cfb = next(r for r in result.json()["models"] if r["sport"] == "americanfootball_ncaaf")
    assert cfb["status"] == "SHADOW_ONLY" and cfb["version"]
    assert len(cfb["market_buckets"]) == 7
    assert all(v["stage"] == "SHADOW_ONLY" for v in cfb["market_buckets"].values())


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("event_id", "wrong", "EVENT_ID_MISMATCH"),
        ("home_team", "Away", "HOME_TEAM_MISMATCH"),
        ("away_team", "Home", "AWAY_TEAM_MISMATCH"),
        ("season", 2025, "SEASON_MISMATCH"),
        ("week", 4, "WEEK_MISMATCH"),
        ("week", None, "UNVERIFIED_WEEK"),
    ],
)
def test_identity_contract(field, value, expected):
    from jabazi.reliability.integrity import Identity, compare_identity
    from datetime import UTC, datetime

    good = Identity("g", "Home", "Away", datetime(2026, 9, 27, tzinfo=UTC), 2026, 3)
    assert expected in compare_identity(replace(good, **{field: value}), good)


def test_duplicates_drift_and_missing_features():
    from jabazi.reliability.integrity import duplicate_event_ids, feature_contract

    quote = q("one", "fanduel", "Over", "1.9", "40.5", "totals")
    assert duplicate_event_ids([quote, replace(quote, event_id="duplicate")]) == {
        "event",
        "duplicate",
    }
    assert not duplicate_event_ids([quote, replace(quote, selection_key="Under")])
    assert feature_contract([100], [0], [1]) == ["FEATURE_DRIFT_0"]
    assert feature_contract([float("nan")], [0], [1]) == ["INVALID_FEATURE_0"]
    assert feature_contract([1], [0], [1], missing_fraction=0.5) == ["EXCESSIVE_MISSING_FEATURES"]


def test_malformed_model_cannot_abort_independent_scanner_price_rows(tmp_path):
    from unittest.mock import patch, MagicMock
    from jabazi.automation import AutomaticScanner
    from jabazi.config import Settings
    from jabazi.persistence.store import Store
    from jabazi.providers.base import ProviderBatch
    from test_score_models import card, artifact

    a = artifact()
    price = card(a)
    store = Store("sqlite:///" + str(tmp_path / "s.db"), initialize=True)
    broken = MagicMock()
    broken.estimate.side_effect = ValueError("broken data")
    batch = ProviderBatch("TEST", price.observed_at, b"{}", (), requests_remaining=100)
    with (
        patch("jabazi.automation.Ledger", return_value=store),
        patch.object(AutomaticScanner, "_active_supported", return_value=[{"key": a["sport"]}]),
        patch("jabazi.automation.TheOddsApiProvider") as provider,
        patch("jabazi.automation.build_price_cards", return_value=[price]),
        patch("jabazi.automation.load_models", return_value=({a["sport"]: broken}, [])),
    ):
        provider.return_value.fetch.return_value = batch
        output = AutomaticScanner(Settings.from_environment()).run()
    assert len(output.actions) == 1 and output.actions[0].model_probability is None
    assert output.actions[0].price.consensus_probability == price.consensus_probability
    assert output.actions[0].stake == 0


def test_market_lane_is_explicit_and_requires_matching_frozen_evidence():
    from jabazi.reliability.market_lane import blend, BlendEvidence

    result = blend(
        0.81, 0.49, sport="nfl", market_bucket="spread", model_version="v", data_healthy=True
    )
    assert result["pure_model_probability"] == 0.81 and result["market_aware_probability"] == 0.49
    assert result["model_weight"] == 0 and not result["approved_for_betting"]
    evidence = BlendEvidence("nfl", "spread", "v", 0.8, 0.85, 1000, 0.20, 0.23, 0.25, "cal-v")
    result = blend(
        0.81,
        0.49,
        sport="nfl",
        market_bucket="spread",
        model_version="v",
        data_healthy=True,
        evidence=evidence,
    )
    assert result["market_aware_probability"] == pytest.approx(0.57)
    with pytest.raises(ValueError):
        blend(
            0.81,
            0.49,
            sport="mlb",
            market_bucket="spread",
            model_version="v",
            data_healthy=True,
            evidence=evidence,
        )

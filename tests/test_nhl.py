"""NHL math, identity, causal features and real scanner plumbing (synthetic prices)."""

import copy
import json
import math
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch

import pytest

from jabazi.automation import AutomaticScanner, select_model
from jabazi.config import Settings
from jabazi.models.nhl_goals import NHLGoalsModel, form, probability, score_grid, team_state
from jabazi.models.nhl_refresh import update_state
from jabazi.models.refresh import BUNDLE_DIR
from jabazi.models.registry import load_models
from jabazi.models.team_elo import timestamp
from jabazi.persistence.store import Store
from jabazi.providers.nhl import rows, SPORT
from jabazi.reliability.layer import evaluate, status_buckets
from test_score_models import card


def artifact():
    return json.loads((BUNDLE_DIR / "nhl_goals.json").read_text())


@pytest.mark.parametrize("h,a,q", [(3, 3, 0.5), (4.7, 2.1, 0.54), (0.2, 7, 0.4), (11, 8, 0.6)])
def test_shared_grid_normalization_and_full_ladder(h, a, q):
    grid = score_grid(h, a, q)
    assert sum(grid.values()) == pytest.approx(1)
    assert all(x != y for x, y in grid)

    def p(m, s, line=None, par=None):
        return probability(grid, m, s, line, "H", "A", par)

    assert p("h2h", "H")["win"] + p("h2h", "A")["win"] == pytest.approx(1)
    for team, other in [("H", "A"), ("A", "H")]:
        values = [p("alternate_spreads", team, x / 2)["win"] for x in range(-19, 20)]
        assert values == sorted(values)
        assert p("spreads", team, -0.5)["win"] == pytest.approx(p("h2h", team)["win"])
        for x in range(-9, 10):
            left = p("spreads", team, x)
            right = p("spreads", other, -x)
            assert left["win"] + right["win"] + left["push"] == pytest.approx(1)
            assert left["push"] == pytest.approx(right["push"])
    for m, par in [("totals", None), ("team_totals", "H"), ("team_totals", "A")]:
        overs = [p(m, "Over", x / 2, par)["win"] for x in range(1, 25)]
        assert overs == sorted(overs, reverse=True)
        for x in range(1, 25):
            o = p(m, "Over", x / 2, par)
            u = p(m, "Under", x / 2, par)
            assert o["win"] + u["win"] + o["push"] == pytest.approx(1)
    # The team-total expectations and game total use exactly the same outcomes.
    eh = sum(hh * w for (hh, aa), w in grid.items())
    ea = sum(aa * w for (hh, aa), w in grid.items())
    assert eh + ea == pytest.approx(sum((hh + aa) * w for (hh, aa), w in grid.items()))
    # OT/SO adds exactly one goal to regulation ties, not a discarded tie or full new score.
    tie = sum(
        math.exp(-h) * h**i / math.factorial(i) * math.exp(-a) * a**i / math.factorial(i)
        for i in range(60)
    )
    assert eh + ea == pytest.approx(h + a + tie, abs=1e-9)


@pytest.mark.parametrize("h,a,q", [(0, 3, 0.5), (float("nan"), 3, 0.5), (3, 13, 0.5), (3, 3, 1)])
def test_invalid_distribution_fails(h, a, q):
    with pytest.raises(ValueError):
        score_grid(h, a, q)


def synthetic_game(period="SO"):
    return {
        "id": 2026020001,
        "season": 20262027,
        "gameType": 2,
        "neutralSite": False,
        "startTimeUTC": "2026-09-29T21:00:00Z",
        "gameState": "OFF",
        "gameScheduleState": "OK",
        "gameOutcome": {"lastPeriodType": period},
        "homeTeam": {"id": 12, "abbrev": "CAR", "score": 4},
        "awayTeam": {"id": 13, "abbrev": "FLA", "score": 3},
    }


@pytest.mark.parametrize("period,reg", [("REG", (4, 3)), ("OT", (3, 3)), ("SO", (3, 3))])
def test_regulation_reconstruction(period, reg):
    g = synthetic_game(period)
    r = rows([{"games": [g, g]}])
    assert len(r) == 1 and (r[0]["regulation_home"], r[0]["regulation_away"]) == reg
    assert timestamp(r[0]["available_at"]) - timestamp(r[0]["starts_at"]) == timedelta(hours=48)


@pytest.mark.parametrize(
    "change", ["margin", "tie", "period", "season", "identity", "duplicate", "neutral"]
)
def test_bad_source_identity_or_settlement_fails(change):
    g = synthetic_game()
    gs = [g]
    if change == "margin":
        g["homeTeam"]["score"] = 6
    if change == "tie":
        g["homeTeam"]["score"] = 3
    if change == "period":
        g["gameOutcome"]["lastPeriodType"] = "UNKNOWN"
    if change == "season":
        g["season"] = 20242025
    if change == "identity":
        g["awayTeam"]["id"] = g["homeTeam"]["id"]
    if change == "neutral":
        del g["neutralSite"]
    if change == "duplicate":
        gs.append(copy.deepcopy(g))
        gs[-1]["startTimeUTC"] = "2026-09-29T20:00:00Z"
    with pytest.raises(ValueError):
        rows([{"games": gs}])


def test_no_preseason_or_future_result_features():
    g = synthetic_game()
    g["gameType"] = 1
    assert rows([{"games": [g]}]) == []
    r = rows([{"games": [synthetic_game()]}])
    now = timestamp(r[0]["starts_at"])
    assert team_state(r, now) == {}
    s = team_state(r, now + timedelta(days=3))
    assert form(s["Carolina Hurricanes"], now, 3) is None
    assert form(s["Carolina Hurricanes"], now + timedelta(days=3), 3) is not None


def test_live_artifact_infers_shadow_and_separates_calibration():
    a = artifact()
    p = card(a)
    model = NHLGoalsModel(a)
    est = model.estimate(p)
    assert est and not est.approved_for_betting
    assert est.feature_snapshot["push_probability"] == 0
    assert est.feature_snapshot["regulation_goal_rates"]
    health = evaluate(p, est, model)
    assert health["model_stage"] == "SHADOW_ONLY"
    assert health["raw_model_probability"] == est.feature_snapshot["raw_model_probability"]
    assert health["calibrated_model_probability"] == float(est.probability)
    assert all(not b["approved_for_betting"] for b in status_buckets(model).values())
    away = p.event.split(" @ ")[0]
    assert float(
        est.probability + model.estimate(replace(p, selection=away)).probability
    ) == pytest.approx(1)


@pytest.mark.parametrize(
    "change",
    [
        "stale",
        "live",
        "price_time",
        "state_time",
        "wrong_game",
        "wrong_season",
        "duplicate",
        "integer",
        "prop",
        "period",
        "unknown",
        "future_training",
        "drift",
    ],
)
def test_inference_fail_closed(change):
    a = artifact()
    p = card(a)
    if change == "stale":
        p = replace(p, stale=True)
    if change == "live":
        p = replace(p, in_play=True)
    if change == "price_time":
        p = replace(p, source_timestamp=p.observed_at - timedelta(minutes=3))
    if change == "state_time":
        a["state_refreshed_at"] = (p.observed_at - timedelta(days=2)).isoformat()
    if change == "wrong_game":
        p = replace(p, starts_at=p.starts_at + timedelta(minutes=10))
    if change == "wrong_season":
        a["active_season"] = 20252026
    if change == "duplicate":
        a["events"].append(a["events"][0])
    if change == "integer":
        p = replace(p, market="totals", selection="Over", line=D(6))
    if change == "prop":
        p = replace(p, market="player_goals", participant="Someone")
    if change == "period":
        p = replace(p, market="h2h_3_way")
    if change == "unknown":
        p = replace(p, event="Fake @ Fake")
    if change == "future_training":
        a["trained_at"] = (p.observed_at + timedelta(seconds=1)).isoformat()
    if change == "drift":
        a["feature_ranges"][0] = [9, 10]
    if change == "duplicate":
        with pytest.raises(ValueError):
            NHLGoalsModel(a)
    else:
        assert NHLGoalsModel(a).estimate(p) is None


def test_team_totals_use_team_model_not_player_model():
    a = artifact()
    p = replace(
        card(a),
        market="team_totals",
        participant=a["events"][0]["home_team"],
        selection="Over",
        line=D("3.5"),
    )
    m = NHLGoalsModel(a)
    assert select_model(p, {SPORT: m}, {}) is m
    assert m.estimate(p) is not None
    assert select_model(replace(p, market="player_goals"), {SPORT: m}, {}) is None


def test_refresh_merges_state_and_rejects_wrong_season():
    a = artifact()
    now = timestamp(a["state_refreshed_at"])
    updated = update_state(a, a["events"], now=now, checksum="test")
    assert (
        updated["model_version"] == a["model_version"] and updated["team_state"] == a["team_state"]
    )
    wrong = copy.deepcopy(a["events"])
    wrong[0]["season"] = 20252026
    with pytest.raises(ValueError):
        update_state(a, wrong, now=now, checksum="test")


def test_failed_store_refresh_does_not_revive_bundle():
    s = Store("sqlite:///:memory:", initialize=True)
    try:
        assert SPORT in load_models(s)[0]
        s.append("game_model", SPORT, {"status": "UNAVAILABLE"})
        models, errors = load_models(s)
        assert SPORT not in models and any(SPORT in e for e in errors)
    finally:
        s.close()


def test_actual_scanner_persists_nhl_team_total(tmp_path, monkeypatch):
    from jabazi.providers.base import ProviderBatch
    from jabazi.domain.models import Decision

    monkeypatch.setenv("JABAZI_ODDS_API_KEY", "test-only")
    a = artifact()
    base = card(a)
    p = replace(
        base, market="team_totals", participant=base.selection, selection="Over", line=D("3.5")
    )
    url = "sqlite:///" + str(tmp_path / "nhl.db")
    s = Store(url, initialize=True)
    s.append("game_model", SPORT, a)
    batch = ProviderBatch("SYNTHETIC_TEST_PRICE", p.observed_at, b"[]", (), requests_remaining=100)
    with (
        patch("jabazi.automation.Ledger", return_value=s),
        patch.object(AutomaticScanner, "_active_supported", return_value=[{"key": SPORT}]),
        patch("jabazi.automation.TheOddsApiProvider") as provider,
        patch("jabazi.automation.build_price_cards", return_value=[p]),
        patch(
            "jabazi.providers.player_features_live.LivePlayerFeatureCollector.sync"
        ) as player_sync,
    ):
        provider.return_value.fetch.return_value = batch
        result = AutomaticScanner(Settings.from_environment()).run()
    assert result.errors == ()
    assert result.actions[0].model_version == a["model_version"]
    assert result.actions[0].model_probability and result.actions[0].decision == Decision.WATCH
    player_sync.assert_not_called()
    s = Store(url)
    assert (
        s.list_records("model_prediction")[0]["payload"]["features"]["settlement"]
        == a["settlement"]
    )
    s.close()


def test_get_model_status_exposes_nhl_buckets(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from jabazi.api import app
    from jabazi.chatgpt_api import scanner_key

    url = "sqlite:///" + str(tmp_path / "status.db")
    Store(url, initialize=True).close()
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "test-service-token-for-nhl-tests-only-0123456789")
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    with TestClient(app) as client:
        r = client.get(
            "/v1/chatgpt/model-status", headers={"Authorization": "Bearer " + scanner_key()}
        )
    assert r.status_code == 200
    nhl = next(r for r in r.json()["models"] if r["sport"] == SPORT)
    assert nhl["version"] == artifact()["model_version"] and nhl["status"] == "SHADOW_ONLY"
    assert len(nhl["market_buckets"]) == 7 and nhl["player_status"] == "UNAVAILABLE"
    assert not nhl["approved_for_betting"]


def test_refresh_stops_before_provider_when_lease_is_lost():
    from jabazi.models.refresh import refresh_models
    s = Store("sqlite:///:memory:", initialize=True)
    try:
        with (patch.object(s, "acquire_lease", side_effect=[True, False]),
              patch("jabazi.models.refresh.fetch_update") as fetch):
            assert refresh_models(s) == {"status": "LEASE_LOST", "models": {}}
            fetch.assert_not_called()
        assert not s.list_records("model_refresh_attempt")
    finally:
        s.close()


def test_opening_week_refresh_with_real_store_does_not_require_completed_games():
    from jabazi.models.nhl_refresh import fetch_update
    a = artifact(); now = timestamp(a["state_refreshed_at"])
    s = Store("sqlite:///:memory:", initialize=True)
    try:
        with patch("jabazi.models.nhl_refresh.fetch_clubs", return_value=(a["events"], "test")):
            updated = fetch_update(a, now=now, result_store=s)
        assert updated["events"] and not s.list_records("prospective_result")
        NHLGoalsModel(updated)
    finally:
        s.close()


def test_failed_refresh_retries_after_backoff_not_six_hours():
    from jabazi.models.refresh import refresh_models
    a = artifact(); now = timestamp(a["state_refreshed_at"])
    s = Store("sqlite:///:memory:", initialize=True)
    try:
        with patch("jabazi.models.refresh.fetch_update", side_effect=ValueError):
            first = refresh_models(s, now=now)
        with patch("jabazi.models.refresh.fetch_update", side_effect=ValueError) as fetch:
            refresh_models(s, now=now+timedelta(minutes=4)); fetch.assert_not_called()
            refresh_models(s, now=now+timedelta(minutes=6)); assert fetch.call_count == len(first)
    finally:
        s.close()

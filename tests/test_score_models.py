import copy
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch

import pytest

from jabazi.domain.models import Decision
from jabazi.domain.recommendation import recommend_price
from jabazi.domain.risk import RiskPolicy
from jabazi.domain.shopping import PriceCard
from jabazi.models.refresh import BUNDLE_DIR, refresh_models, schedule_mlb
from jabazi.models.registry import load_models
from jabazi.models.score_distribution import ScoreDistributionModel, outcome_probability
from jabazi.models.team_elo import timestamp
from jabazi.persistence.store import Store


def artifact(short="nfl"):
    return json.loads((BUNDLE_DIR / f"{short}_scores.json").read_text())


def card(a):
    observed = timestamp(a["state_refreshed_at"]) + timedelta(seconds=1)
    event = next(e for e in a["events"] if timestamp(e["starts_at"]) > observed)
    return PriceCard(
        a["sport"],
        "test-event",
        event["away_team"] + " @ " + event["home_team"],
        "h2h",
        None,
        event["home_team"],
        None,
        {"Test": D(2)},
        "Test",
        D(2),
        D(".5"),
        D(0),
        D(0),
        False,
        False,
        ("test-quote",),
        observed,
        observed,
        timestamp(event["starts_at"]),
    )


@pytest.mark.parametrize("short", ["nfl", "mlb"])
def test_bundled_models_infer_and_cannot_self_promote(short):
    a = artifact(short)
    a["approved_for_betting"] = True
    model = ScoreDistributionModel(a)
    price = card(a)
    estimate = model.estimate(price)
    assert estimate is not None and D(0) < estimate.probability < D(1)
    assert not estimate.approved_for_betting
    action = recommend_price(
        price,
        RiskPolicy(D(3000)),
        estimate.probability,
        estimate.uncertainty,
        model_validated=estimate.approved_for_betting,
    )
    assert action.decision == Decision.WATCH and action.stake == 0
    away = price.event.split(" @ ")[0]
    other = model.estimate(replace(price, selection=away))
    assert abs(estimate.probability + other.probability - 1) < D("1e-12")
    over = model.estimate(
        replace(
            price, market="totals", selection="Over", line=D("44.5") if short == "nfl" else D("8.5")
        )
    )
    under = model.estimate(
        replace(
            price,
            market="totals",
            selection="Under",
            line=D("44.5") if short == "nfl" else D("8.5"),
        )
    )
    assert over and under and abs(over.probability + under.probability - 1) < D("1e-12")


def test_model_rejects_stale_unknown_live_and_unsupported_inputs():
    a = artifact()
    model = ScoreDistributionModel(a)
    p = card(a)
    for change in (
        {"in_play": True},
        {"market": "player_anytime_td"},
        {"market": "totals_h1"},
        {"event": "Unknown @ Unknown"},
        {"starts_at": p.starts_at + timedelta(minutes=10)},
        {"observed_at": p.observed_at + timedelta(days=3)},
    ):
        assert model.estimate(replace(p, **change)) is None
    a["events"] = []
    assert ScoreDistributionModel(a).estimate(p) is None


def test_feature_results_cannot_arrive_after_observation():
    a = artifact()
    p = card(a)
    for games in a["team_state"].values():
        games[-1][3] = (p.observed_at + timedelta(minutes=5)).isoformat()
    assert ScoreDistributionModel(a).estimate(p) is None


def test_push_and_spread_sign_are_explicit():
    samples = [(24, 21), (21, 24), (28, 21), (21, 21)]
    assert outcome_probability(samples, "spreads", "Home", -3, "Home", "Away") == {
        "win": 0.25,
        "push": 0.25,
        "loss": 0.5,
    }
    assert outcome_probability(samples, "totals", "Over", 45, "Home", "Away") == {
        "win": 0.25,
        "push": 0.5,
        "loss": 0.25,
    }
    assert (
        outcome_probability(samples, "team_totals", "Over", 23.5, "Home", "Away", "Home")["win"]
        == 0.5
    )
    assert (
        outcome_probability(samples, "team_totals", "Over", 23.5, "Home", "Away", "Unknown") is None
    )


def test_nonfinite_artifact_rejected():
    a = artifact()
    a["coefficients"][0][0] = float("nan")
    with pytest.raises(ValueError):
        ScoreDistributionModel(a)


def test_mlb_venue_requires_verified_home_match():
    now = datetime.now(UTC)
    game = {
        "gameDate": (now + timedelta(days=1)).isoformat(),
        "gameType": "R",
        "gamePk": 5,
        "status": {"abstractGameState": "Preview"},
        "teams": {
            "home": {"team": {"id": 1, "name": "H"}},
            "away": {"team": {"id": 2, "name": "A"}},
        },
        "venue": {"id": 99},
    }
    payload = {"dates": [{"games": [game]}]}
    assert not schedule_mlb(payload, now)
    assert not schedule_mlb(payload, now, {1: 100})
    assert schedule_mlb(payload, now, {1: 99})[0]["neutral_site"] is False


def test_failed_cloud_refresh_overrides_bundled_file_and_throttles():
    s = Store("sqlite:///:memory:", initialize=True)
    try:
        with patch("jabazi.models.refresh.fetch_update", side_effect=OSError("test")) as fetch:
            result = refresh_models(s)
            assert all(result[k]["status"] == "UNAVAILABLE" for k in ("nfl", "mlb"))
            assert refresh_models(s) == {"nfl": "NOT_DUE", "mlb": "NOT_DUE"}
            assert fetch.call_count == 2
        models, errors = load_models(s)
        assert "americanfootball_nfl" not in models and "baseball_mlb" not in models
        assert len(errors) >= 2
    finally:
        s.close()


def test_actual_scanner_uses_cloud_artifact_and_archives_prediction(tmp_path):
    from jabazi.automation import AutomaticScanner
    from jabazi.config import Settings
    from jabazi.providers.base import ProviderBatch

    a = artifact()
    p = card(a)
    url = "sqlite:///" + str(tmp_path / "scan.db")
    s = Store(url, initialize=True)
    s.append("game_model", a["sport"], a)
    batch = ProviderBatch("TEST_ONLY", p.observed_at, b"{}", (), requests_remaining=100)
    with (
        patch("jabazi.automation.Ledger", return_value=s),
        patch.object(AutomaticScanner, "_active_supported", return_value=[{"key": a["sport"]}]),
        patch("jabazi.automation.TheOddsApiProvider") as provider,
        patch("jabazi.automation.build_price_cards", return_value=[p]),
    ):
        provider.return_value.fetch.return_value = batch
        result = AutomaticScanner(Settings.from_environment()).run()
    assert result.errors == ()
    assert result.actions[0].model_probability is not None
    assert result.actions[0].model_version == a["model_version"]
    assert result.actions[0].decision == Decision.WATCH
    s = Store(url)
    assert len(s.list_records("model_prediction")) == 1
    assert s.list_records("scan_run")[0]["payload"]["modeled_actions"] == 1
    s.close()


@pytest.mark.parametrize("short", ["nfl", "mlb"])
def test_fitted_probability_reaches_private_chat_results(tmp_path, monkeypatch, short):
    """Real registry/inference/scanner/API/storage/presentation; no paid data calls."""
    from uuid import uuid4
    from jabazi import chatgpt_api as bridge
    from jabazi.automation import AutomaticScanner
    from jabazi.providers.base import ProviderBatch

    monkeypatch.setenv("JABAZI_ODDS_API_KEY", "test-only")
    a = artifact(short)
    p = card(a)
    estimate = ScoreDistributionModel(a).estimate(p)
    s = Store("sqlite:///" + str(tmp_path / "chat-model.db"), initialize=True)
    s.append("game_model", a["sport"], a)
    scan_id = str(uuid4())
    bridge.submit(s, scan_id)
    # High market-relative values must not crowd real model estimates out of
    # the bounded chat response. No model exists for these research-only rows.
    unmodeled = [
        replace(p, sport="basketball_nba", event_id=f"other-{i}", market_relative_ev=D(".9"))
        for i in range(270)
    ]
    batch = ProviderBatch("TEST_ONLY", p.observed_at, b"{}", (), requests_remaining=100)
    try:
        with (
            patch.object(bridge, "store_factory", return_value=s),
            patch.object(s, "close"),
            patch("jabazi.automation.Ledger", return_value=s),
            patch.object(
                AutomaticScanner,
                "_active_supported",
                return_value=[
                    {"key": a["sport"]},
                    {"key": "basketball_nba"},
                ],
            ),
            patch("jabazi.automation.TheOddsApiProvider") as provider,
            patch("jabazi.automation.build_price_cards", side_effect=[[p], unmodeled]),
        ):
            provider.return_value.fetch.return_value = batch
            bridge.run_background(scan_id)
        page = bridge.scan_page(s, scan_id, now=p.observed_at)
        assert page.status == "COMPLETE" and page.errors == []
        assert page.total_actions == 271 and page.total_returned_actions == 260
        assert page.truncated and page.result_ordering == "model_coverage_first"
        row = page.actions[0]
        assert row["sport"] == a["sport"]
        assert D(row["model_probability"]) == estimate.probability
        assert row["model_version"] == estimate.model_version
        assert D(row["consensus_probability"]) == p.consensus_probability
        assert D(row["probability_edge"]) == estimate.probability - p.consensus_probability
        assert D(row["uncertainty"]) == estimate.uncertainty
        assert row["probability_status"] == "SHADOW_ONLY"
        assert row["decision"] == "WATCH" and row["stake_dollars"] == "0"
        assert row["expected_roi"] is None and row["maximum_playable_price"] is None
        assert page.model_coverage["modeled_actions"] == 1
        assert page.model_coverage["returned_modeled_actions"] == 1
        assert page.model_coverage["returned_unmodeled_actions"] == 259
        assert page.actions[1]["model_probability"] is None
        assert page.actions[1]["probability_status"] == "UNAVAILABLE"
        assert not page.betting_enabled
        archived = s.list_records("model_prediction")[0]["payload"]
        assert D(archived["probability"]) == estimate.probability
        assert archived["model_version"] == estimate.model_version
    finally:
        s.close()


def test_fitting_and_residuals_do_not_use_diagnostic_labels(tmp_path):
    pytest.importorskip("sklearn")
    from jabazi.research.train_scores import train

    games = []
    for year in (2023, 2024, 2025):
        for i in range(125):
            games.append(
                {
                    "game_id": f"{year}-{i}",
                    "season": year,
                    "starts_at": (
                        datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=i * 2)
                    ).isoformat(),
                    "home_team": "H",
                    "away_team": "A",
                    "home_score": 14 + i % 17,
                    "away_score": 10 + i % 13,
                    "neutral_site": False,
                }
            )
    payload = {"sport": "americanfootball_nfl", "games": games}
    p = tmp_path / "input.json"
    p.write_text(json.dumps(payload))
    train(p, tmp_path / "a", "nfl")
    changed = copy.deepcopy(payload)
    for g in changed["games"]:
        if g["season"] == 2025:
            g["home_score"] += 50
    p.write_text(json.dumps(changed))
    train(p, tmp_path / "b", "nfl")
    a = json.loads((tmp_path / "a/artifact.json").read_text())
    b = json.loads((tmp_path / "b/artifact.json").read_text())
    for key in ("coefficients", "intercepts", "mean", "scale", "residual_pairs"):
        assert a[key] == b[key]


def test_scanner_keeps_feed_events_when_no_price_card_survives(tmp_path):
    import json
    from jabazi.automation import AutomaticScanner
    from jabazi.config import Settings
    from jabazi.discord_sheets import archive_sheets, latest_sheet
    from jabazi.providers.base import ProviderBatch
    from jabazi.sheet_images import slate_blocks

    url = "sqlite:///" + str(tmp_path / "empty-prices.db")
    s = Store(url, initialize=True)
    batch = ProviderBatch(
        "TEST_ONLY",
        datetime.now(UTC),
        json.dumps(
            [
                {
                    "id": "unpriced",
                    "away_team": "Away",
                    "home_team": "Home",
                    "commence_time": "2026-09-24T01:00:00Z",
                    "bookmakers": [],
                }
            ]
        ).encode(),
        (),
        requests_remaining=100,
    )
    with (
        patch("jabazi.automation.Ledger", return_value=s),
        patch.object(
            AutomaticScanner, "_active_supported", return_value=[{"key": "americanfootball_nfl"}]
        ),
        patch("jabazi.automation.TheOddsApiProvider") as provider,
        patch("jabazi.automation.load_models", return_value=({}, [])),
    ):
        provider.return_value.fetch.return_value = batch
        result = AutomaticScanner(Settings.from_environment()).run()
    assert result.actions == () and not result.errors
    s = Store(url)
    try:
        archive_sheets(s, result)
        blocks = slate_blocks(latest_sheet(s), "nfl", 0)
        assert len(blocks) == 1 and blocks[0]["event_id"] == "unpriced"
        assert blocks[0]["rows"] == []
    finally:
        s.close()

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.domain.shopping import PriceCard
from jabazi.research.same_game import evaluate_same_game, scan_candidates, _scenarios
from jabazi.sgp_api import SameGameRequest
from test_score_models import artifact, card
from jabazi.models.score_distribution import ScoreDistributionModel

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def prices():
    base = PriceCard(
        "americanfootball_nfl",
        "e",
        "Away @ Home",
        "spreads",
        None,
        "Home",
        D("-.5"),
        {},
        "",
        D(2),
        D(".5"),
        D(0),
        D(0),
        False,
        False,
        (),
        NOW,
        NOW,
        NOW + timedelta(days=1),
    )
    return [base, replace(base, market="totals", selection="Over", line=D("40.5"))]


def scenarios(rows=None):
    est = SimpleNamespace(
        uncertainty=D(".08"),
        model_version="synthetic-test",
        feature_snapshot={"schedule_game_id": "e"},
    )
    return (
        rows or [[True, True], [False, False]],
        [D(".5"), D(".5")],
        [est, est],
        "full_game_including_overtime",
    )


def evaluate(ps=None, **kw):
    with patch("jabazi.research.same_game._scenarios", return_value=scenarios()):
        return evaluate_same_game(ps or prices(), object(), now=NOW, **kw)


def offer(result, **kw):
    return (
        dict(
            candidate_id=result["candidate_id"],
            quote_id="book-slip-123",
            sportsbook="test",
            decimal_odds="4",
            quoted_at=NOW.isoformat(),
            settlement=result["settlement"],
        )
        | kw
    )


def test_shared_outcomes_not_independent_product_and_exact_price():
    r = evaluate()
    assert r["joint_probability"] == D(".5")
    assert r["independence_diagnostic"] == D(".25")
    assert r["pairwise_correlations"][0]["phi"] == pytest.approx(1)
    assert r["expected_roi"] is None and r["status"] == "PRICE_CHECK"
    priced = evaluate(offer=offer(r))
    assert priced["expected_roi"] == D(1)
    assert priced["risk_adjusted_roi"] == D(".36")
    assert priced["status"] == "RESEARCH_ONLY"
    assert priced["recommended_stake_units"] is None
    assert not priced["cash_influence"] and not priced["approved_for_betting"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"candidate_id": "x" * 64}, "COMBINED_QUOTE_IDENTITY_MISMATCH"),
        ({"settlement": "regulation"}, "SPORTSBOOK_SETTLEMENT_CONFIRMATION_REQUIRED"),
        (
            {"quoted_at": (NOW - timedelta(seconds=121)).isoformat()},
            "STALE_OR_FUTURE_COMBINED_QUOTE",
        ),
        ({"quoted_at": (NOW + timedelta(seconds=1)).isoformat()}, "STALE_OR_FUTURE_COMBINED_QUOTE"),
        ({"quoted_at": "2026-10-02T00:00:00"}, "INVALID_COMBINED_QUOTE"),
        ({"decimal_odds": "NaN"}, "INVALID_COMBINED_QUOTE"),
    ],
)
def test_quote_failures_suppress_ev(change, reason):
    r = evaluate()
    r = evaluate(offer=offer(r, **change))
    assert reason in r["reasons"] and r["expected_roi"] is None


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("event_id", "other", "SAME_EVENT_REQUIRED"),
        ("stale", True, "STALE_OR_FUTURE_LEG_DATA"),
        ("source_timestamp", NOW - timedelta(minutes=3), "STALE_OR_FUTURE_LEG_DATA"),
        ("observed_at", NOW + timedelta(seconds=1), "STALE_OR_FUTURE_LEG_DATA"),
        ("in_play", True, "PREGAME_ONLY"),
        ("market", "player_pass_yds", "JOINT_PLAYER_MODEL_UNAVAILABLE"),
    ],
)
def test_unsupported_and_bad_inputs_fail_closed(field, value, reason):
    ps = prices()
    ps[1] = replace(ps[1], **{field: value})
    r = evaluate(ps)
    assert r["status"] == "UNAVAILABLE" and reason in r["reasons"]
    assert r["joint_probability"] is None


def test_duplicate_regular_and_alternate_leg():
    p = prices()[0]
    r = evaluate([p, replace(p, market="alternate_spreads", line=D("-.50"))])
    assert r["reasons"] == ["REQUIRE_2_TO_4_DISTINCT_LEGS"]


def test_negative_dependence_and_impossible_combination():
    with patch(
        "jabazi.research.same_game._scenarios",
        return_value=scenarios([[True, False], [False, True]]),
    ):
        r = evaluate_same_game(prices(), object(), now=NOW)
    assert r["joint_probability"] == 0 and r["status"] == "PASS"
    assert r["pairwise_correlations"][0]["phi"] == pytest.approx(-1)


@pytest.mark.parametrize("short", ["nfl", "mlb"])
def test_real_score_adapter_uses_shared_model_scores(short):
    a = artifact(short)
    model = ScoreDistributionModel(a)
    p = card(a)
    ps = [
        replace(p, market="spreads", line=D("-.5")),
        replace(p, market="totals", selection="Over", line=D("8.5" if short == "mlb" else "40.5")),
    ]
    r = evaluate_same_game(ps, model, now=p.observed_at)
    assert r["status"] == "PRICE_CHECK", r
    assert 0 < r["joint_probability"] <= min(r["marginal_probabilities"])
    assert not r["approved_for_betting"]


def test_tied_score_mass_cannot_be_conditioned_away_for_moneyline():
    a = artifact("nfl")
    model = ScoreDistributionModel(a)
    p = card(a)
    with patch("jabazi.research.same_game.score_samples", return_value=[(20, 20), (30, 10)]):
        with pytest.raises(ValueError, match="PUSH_OR_TIE_REPRICING_UNSUPPORTED"):
            _scenarios(model, [p, replace(p, market="totals", selection="Over", line=D("40.5"))])


def test_screen_is_bounded_and_zero_stake():
    actions = [SimpleNamespace(price=p) for p in prices()]
    with patch("jabazi.research.same_game._scenarios", return_value=scenarios()):
        r = scan_candidates(actions, {prices()[0].sport: object()}, now=NOW)
    assert r["pairs_examined"] == 1 and r["candidates_found"] == 1
    assert r["candidates"][0]["recommended_stake_units"] is None


def test_endpoint_auth_and_request_validation():
    with TestClient(app) as client:
        r = client.post(
            "/v1/chatgpt/same-game-parlay",
            json={"scan_id": "2c2267a0-9a9c-461f-85db-fef917767720", "leg_indexes": [0, 1]},
        )
        assert r.status_code in (401, 503)
    with pytest.raises(ValueError):
        SameGameRequest.model_validate(
            {"scan_id": "2c2267a0-9a9c-461f-85db-fef917767720", "leg_indexes": [True, 1]}
        )


def test_nhl_adapter_retains_weighted_ot_grid():
    from test_nhl import artifact as nhl_artifact
    from jabazi.models.nhl_goals import NHLGoalsModel

    a = nhl_artifact()
    model = NHLGoalsModel(a)
    p = card(a)
    ps = [p, replace(p, market="totals", selection="Over", line=D("5.5"))]
    r = evaluate_same_game(ps, model, now=p.observed_at)
    assert r["status"] == "PRICE_CHECK", r
    assert 0 < r["joint_probability"] <= min(r["marginal_probabilities"])
    assert r["settlement"] == "full_game_including_ot_one_shootout_deciding_goal"


def test_endpoint_uses_only_archived_legs_and_rejects_unhealthy_scan(tmp_path, monkeypatch):
    import json
    from uuid import uuid4
    from jabazi import chatgpt_api as bridge
    from jabazi.persistence.store import Store
    from jabazi.sgp_api import evaluate_request
    from fastapi import HTTPException

    store = Store("sqlite:///" + str(tmp_path / "sgp.db"), initialize=True)
    ps = prices()
    # Archive actual wire fields, no client-supplied probabilities/scenarios.
    rows = [
        dict(
            sport=p.sport,
            event_id=p.event_id,
            event=p.event,
            market=p.market,
            participant=p.participant,
            selection=p.selection,
            line=str(p.line),
            best_decimal="2",
            stale=False,
            in_play=False,
            observed_at=NOW.isoformat(),
            source_timestamp=NOW.isoformat(),
            starts_at=p.starts_at.isoformat(),
        )
        for p in ps
    ]
    with (
        patch.object(bridge, "store_factory", return_value=store),
        patch.object(store, "close"),
        patch("jabazi.models.registry.load_models", return_value=({ps[0].sport: object()}, [])),
        patch("jabazi.research.same_game._scenarios", return_value=scenarios()),
        patch("jabazi.sgp_api.datetime") as clock,
    ):
        clock.now.return_value = NOW
        for status in ["COMPLETE", "PARTIAL"]:
            scan_id = str(uuid4())
            store.append(
                "chatgpt_scan_result",
                scan_id,
                {"status": status, "actions": rows, "errors": []},
                scan_id,
            )
            body = SameGameRequest(scan_id=scan_id, leg_indexes=[0, 1])
            if status == "COMPLETE":
                result = json.loads(evaluate_request(body).body)
                assert result["joint_probability"] == "0.5"
                assert result["scan_id"] == scan_id
                assert result["recommended_stake_units"] is None
                with pytest.raises(HTTPException) as exc:
                    evaluate_request(SameGameRequest(scan_id=scan_id, leg_indexes=[0, 2]))
                assert exc.value.status_code == 422
            else:
                with pytest.raises(HTTPException) as exc:
                    evaluate_request(body)
                assert exc.value.status_code == 409
    store.close()


def test_retrieved_candidates_expire_without_mutating_archive():
    from jabazi.chatgpt_api import present_coverage

    r = evaluate()
    coverage = {"same_game_parlays": {"candidates": [r]}}
    shown = present_coverage(coverage, NOW + timedelta(seconds=121))
    assert shown["same_game_parlays"]["candidates"][0]["status"] == "STALE_DATA"
    assert r["status"] == "PRICE_CHECK"


@pytest.mark.parametrize("count", [3, 4])
def test_real_model_three_and_four_leg_outcomes(count):
    a = artifact("nfl")
    model = ScoreDistributionModel(a)
    p = card(a)
    away = p.event.split(" @ ")[0]
    ps = [
        replace(p, market="spreads", line=D("-.5")),
        replace(p, market="totals", selection="Over", line=D("40.5")),
        replace(p, market="team_totals", participant=p.selection, selection="Over", line=D("20.5")),
        replace(p, market="team_totals", participant=away, selection="Under", line=D("30.5")),
    ][:count]
    r = evaluate_same_game(ps, model, now=p.observed_at)
    assert r["status"] == "PRICE_CHECK", r
    assert len(r["marginal_probabilities"]) == count
    assert len(r["pairwise_correlations"]) == count * (count - 1) / 2
    assert 0 < r["joint_probability"] <= min(r["marginal_probabilities"])

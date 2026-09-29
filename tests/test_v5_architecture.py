from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from jabazi.models.game_distribution import GameDistribution
from jabazi.models.scenario_engine import same_event_ticket, cross_event_ticket, overlap
from jabazi.models.opportunity import OpportunityEstimate, required_unit, opportunity_adjustment
from jabazi.reliability.v5 import kill_switch, segmented_calibration
from jabazi.research.market_intelligence import snapshot_payload, clv


def distribution():
    samples=[]
    for i in range(200):
        samples.append((20+(i%11),17+((i*3)%10)))
    return GameDistribution(tuple(samples))


def test_same_event_joint_uses_shared_scenarios_not_marginal_product():
    legs=(
        {"event_id":"g1","market":"h2h","selection":"Home","line":None},
        {"event_id":"g1","market":"totals","selection":"Over","line":42.5},
    )
    ticket=same_event_ticket(distribution(),legs,home="Home",away="Away",event_id="g1")
    assert ticket.method=="shared_game_scenarios"
    assert ticket.independence_assumption is False
    assert 0<=ticket.uncertainty_low<=ticket.probability<=ticket.uncertainty_high<=1
    assert ticket.approved_for_betting is False


def test_cross_event_ticket_labels_independence_and_propagates_bounds():
    ticket=cross_event_ticket((
        {"event_id":"a","market":"h2h","selection":"A","probability":.6,"uncertainty_low":.55,"uncertainty_high":.65},
        {"event_id":"b","market":"h2h","selection":"B","probability":.7,"uncertainty_low":.64,"uncertainty_high":.75},
    ))
    assert ticket.probability==pytest.approx(.42)
    assert ticket.independence_assumption is True
    assert ticket.uncertainty_low==pytest.approx(.55*.64)


def test_overlap_detects_common_event_and_subject():
    a=cross_event_ticket((
        {"event_id":"a","market":"h2h","selection":"A","probability":.6},
        {"event_id":"b","market":"h2h","selection":"B","probability":.7},
    ))
    b=cross_event_ticket((
        {"event_id":"a","market":"h2h","selection":"A","probability":.61},
        {"event_id":"c","market":"h2h","selection":"C","probability":.68},
    ))
    o=overlap(a,b)
    assert o["same_event"] is True and o["same_subject"] is True


def test_opportunity_contract_and_bounded_adjustment():
    e=OpportunityEstimate(36,32,40,"minutes","nba-minutes-v1",True)
    assert required_unit("basketball_nba","player_points")=="minutes"
    assert opportunity_adjustment(baseline_opportunity=30,estimate=e)==pytest.approx(1.2)


def card():
    now=datetime(2026,9,28,18,tzinfo=UTC)
    return SimpleNamespace(
        sport="americanfootball_nfl",event_id="g1",starts_at=now+timedelta(hours=5),
        market="h2h",selection="Home",participant=None,line=None,
        source_timestamp=now,book_prices={"A":Decimal("2.00"),"B":Decimal("1.95")},
        best_book="A",best_decimal=Decimal("2.00"),consensus_probability=Decimal("0.51"),
        quote_ids=["q1","q2"],
    )


def test_market_snapshot_and_clv_are_exact_identity():
    entry=snapshot_payload(card(),observed_at=datetime(2026,9,28,18,tzinfo=UTC))
    c=card(); c.best_decimal=Decimal("1.80"); c.consensus_probability=Decimal("0.56")
    close=snapshot_payload(c,observed_at=datetime(2026,9,28,21,tzinfo=UTC))
    result=clv(entry,close)
    assert result["clv_probability_points"]==pytest.approx(.05)
    assert result["clv_decimal"]==pytest.approx(.2)


def test_kill_switch_quarantines_bad_identity_or_data():
    assert kill_switch(data_health=False,drift=False,calibration_ece=None,recent_brier_delta=None,identity_failures=0)["state"]=="QUARANTINED"
    assert kill_switch(data_health=True,drift=False,calibration_ece=.09,recent_brier_delta=None,identity_failures=0,sample_count=200)["state"]=="WATCH"


def test_segmented_calibration_keeps_market_and_edge_bands_separate():
    rows=[
        {"sport":"nfl","bucket":"moneyline","probability":.60,"market_probability":.55,"outcome":1},
        {"sport":"nfl","bucket":"moneyline","probability":.62,"market_probability":.56,"outcome":0},
        {"sport":"nfl","bucket":"moneyline","probability":.48,"market_probability":.47,"outcome":1},
    ]
    groups=segmented_calibration(rows)
    assert len(groups)==2
    assert sum(g["n"] for g in groups)==3


def test_postmortem_classifies_verified_systematic_causes_before_variance():
    from jabazi.research.postmortem import classify, summarize

    assert classify(
        prediction={"probability": 0.7},
        result={"outcome": 0},
        context={"stale_data": True},
    )["classification"] == "STALE_DATA"
    rows = [
        {"classification": "NORMAL_VARIANCE"},
        {"classification": "BAD_PROBABILITY"},
    ] * 10
    report = summarize(rows)
    assert report["n"] == 20
    assert report["enough_for_pattern_review"] is True


def test_granular_snapshot_is_research_only_and_immutable():
    from jabazi.persistence.store import Store
    from jabazi.research.granular import archive_granular_snapshot

    store = Store("sqlite:///:memory:", initialize=True)
    try:
        archived = archive_granular_snapshot(
            store,
            sport="americanfootball_nfl",
            event_id="g1",
            participant="Receiver One",
            starts_at="2026-10-01T00:00:00+00:00",
            available_at="2026-09-30T18:00:00+00:00",
            features={"mean10_target_share": 0.24, "mean10_receiving_epa": 3.1},
            provider="nflverse weekly player stats",
            source_checksum="abc",
            schema_version="nfl-granular-weekly-v1",
        )
        assert archived is True
        row = store.list_records("granular_feature_snapshot", 1)[0]["payload"]
        assert row["research_only"] is True
        assert row["cash_influence"] is False
        assert row["features"]["mean10_target_share"] == pytest.approx(0.24)
    finally:
        store.close()


def test_exact_clv_requires_matching_entry_and_close_snapshots():
    from jabazi.persistence.store import Store
    from jabazi.research.market_intelligence import (
        archive_snapshot,
        archive_closing_snapshot,
        exact_clv_from_store,
    )

    store = Store("sqlite:///:memory:", initialize=True)
    try:
        entry_card = card()
        archive_snapshot(
            store,
            entry_card,
            observed_at=datetime(2026, 9, 28, 18, tzinfo=UTC),
        )
        close_card = card()
        close_card.best_decimal = Decimal("1.80")
        close_card.consensus_probability = Decimal("0.56")
        close_card.observed_at = datetime(2026, 9, 28, 21, tzinfo=UTC)
        close_card.source_timestamp = datetime(2026, 9, 28, 21, tzinfo=UTC)
        archive_closing_snapshot(store, close_card)
        result = exact_clv_from_store(
            store,
            event_id="g1",
            market="h2h",
            selection="Home",
            line=None,
            participant=None,
            entry_observed_at="2026-09-28T18:00:00+00:00",
        )
        assert result["status"] == "EXACT_CLV"
        assert result["clv_probability_points"] == pytest.approx(0.05)
    finally:
        store.close()


def test_opportunity_model_trains_chronologically_and_stays_validating():
    from jabazi.models.train_opportunity import fit_opportunity_model, estimate_opportunity

    rows = []
    starts = [
        "2023-01-10T00:00:00+00:00", "2023-02-10T00:00:00+00:00",
        "2023-03-10T00:00:00+00:00", "2024-02-10T00:00:00+00:00",
        "2024-03-10T00:00:00+00:00", "2024-04-10T00:00:00+00:00",
        "2025-02-10T00:00:00+00:00", "2025-03-10T00:00:00+00:00",
        "2025-04-10T00:00:00+00:00",
    ]
    for i, start in enumerate(starts):
        dt = datetime.fromisoformat(start)
        rows.append({
            "event_id": f"e{i}",
            "player_id": "p1",
            "prediction_at": (dt - timedelta(hours=6)).isoformat(),
            "features_available_at": (dt - timedelta(days=2)).isoformat(),
            "starts_at": dt.isoformat(),
            "result_available_at": (dt + timedelta(days=1)).isoformat(),
            "features": {"mean5_minutes": 28.0 + i, "is_home": float(i % 2)},
            "observed_opportunity": 29.0 + i,
            "opportunity_unit": "minutes",
        })
    doc = {
        "manifest": {
            "sport": "basketball_nba",
            "provider": "TEST",
            "source_checksum": "abc",
        },
        "rows": rows,
    }
    artifact = fit_opportunity_model(
        doc,
        train_before="2024-01-01T00:00:00+00:00",
        test_before="2025-01-01T00:00:00+00:00",
        minimum_per_split=2,
    )
    assert artifact["stage"] == "VALIDATING"
    assert artifact["approved_for_betting"] is False
    estimate = estimate_opportunity(
        artifact, {"mean5_minutes": 35.0, "is_home": 1.0}
    )
    assert estimate.unit == "minutes"
    assert estimate.low <= estimate.mean <= estimate.high
    assert estimate.approved_for_betting is False


def test_linear_edge_explanation_is_explicitly_noncausal():
    from jabazi.models.explain import explanation

    artifact = {
        "feature_names": ["a", "b"],
        "scaler": {"mean": [0, 10], "scale": [1, 2]},
        "parameters": {"coef": [2, -1], "intercept": 0},
    }
    result = explanation(artifact, {"a": 2, "b": 8})
    assert result["causal"] is False
    assert result["drivers"][0]["feature"] == "a"
    assert result["drivers"][0]["direction"] == "higher"


def test_opportunity_regime_proxy_flags_large_recent_shift():
    from jabazi.reliability.regime import opportunity_proxy

    stable = opportunity_proxy({
        "mean3_opportunities": 10,
        "mean10_opportunities": 9.5,
    })
    shifted = opportunity_proxy({
        "mean3_opportunities": 16,
        "mean10_opportunities": 10,
    })
    assert stable["detected"] is False
    assert shifted["detected"] is True
    assert shifted["uncertainty_multiplier"] > 1


def test_adversarial_review_requires_sourced_pregame_evidence():
    from jabazi.persistence.store import Store
    from jabazi.research.adversarial import freeze_review, latest_review

    store = Store("sqlite:///:memory:", initialize=True)
    try:
        payload = {
            "sport": "americanfootball_nfl",
            "event_id": "g1",
            "starts_at": "2026-10-01T00:00:00+00:00",
            "market": "h2h",
            "selection": "Home",
            "participant": None,
            "line": None,
            "reviewed_at": "2026-09-30T20:00:00+00:00",
            "outcome": "SURVIVES_CHALLENGE",
            "thesis": "Test-only thesis",
            "sources": [{
                "url": "https://example.com/official",
                "tier": "OFFICIAL",
                "observed_at": "2026-09-30T19:55:00+00:00",
                "finding": "No material lineup change.",
                "contrary": False,
            }],
        }
        freeze_review(
            store, payload,
            now=datetime(2026, 9, 30, 20, 1, tzinfo=UTC),
        )
        c = card()
        c.starts_at = datetime(2026, 10, 1, 0, tzinfo=UTC)
        review = latest_review(
            store, c,
            now=datetime(2026, 9, 30, 20, 30, tzinfo=UTC),
        )
        assert review is not None
        assert review["outcome"] == "SURVIVES_CHALLENGE"
        assert review["cash_influence"] is False
    finally:
        store.close()


def test_portfolio_correlation_key_can_bind_before_new_exposure():
    from jabazi.domain.portfolio import Position, Limits, allocate

    limits = Limits(Decimal("3000"), correlation=Decimal(".04"))
    existing = Position(
        Decimal("120"), "americanfootball_nfl", "g1",
        theses=frozenset({"favorite_side"}), betting_date="2026-09-29",
        correlation_keys=frozenset({"event:g1"}),
    )
    proposal = Position(
        Decimal("0"), "americanfootball_nfl", "g1",
        theses=frozenset({"favorite_side"}), betting_date="2026-09-29",
        correlation_keys=frozenset({"event:g1"}),
    )
    result = allocate(
        Decimal(".60"), Decimal("2.0"), proposal, [existing], limits
    )
    assert result.dollars == 0
    assert "correlation:event:g1" in result.reasons

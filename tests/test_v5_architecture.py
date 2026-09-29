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

from datetime import UTC, datetime, timedelta
from dataclasses import replace
from decimal import Decimal as D
import pytest
from jabazi.research.parlays import evaluate_parlay
from jabazi.research.closing import closing_proxy
from jabazi.domain.models import Quote, DataQuality


def test_correlated_parlay_prices_joint_probability_and_actual_offer():
    now = datetime.now(UTC)
    result = evaluate_parlay(
        leg_ids=["qb", "wr"],
        outcomes=[(True, True), (False, False)],
        weights=[".5", ".5"],
        offered_decimal=2,
        quoted_at=now,
        now=now,
        model_version="TEST",
        provenance="SYNTHETIC TEST SCENARIOS",
    )
    assert result["joint_probability"] == D(".5")
    assert result["pairwise_correlations"][0]["phi"] == pytest.approx(1)
    assert result["status"] == "PASS"  # A 2x payout is fair, not positive EV.
    assert result["expected_roi"] == 0


def test_stale_parlay_offer_cannot_qualify():
    now = datetime.now(UTC)
    result = evaluate_parlay(
        leg_ids=["a", "b"],
        outcomes=[(True, True), (False, False)],
        weights=[".5", ".5"],
        offered_decimal=3,
        quoted_at=now - timedelta(minutes=5),
        now=now,
        model_version="TEST",
        provenance="SYNTHETIC TEST SCENARIOS",
    )
    assert result["status"] == "PASS"
    assert "STALE_OR_FUTURE_PAYOUT" in result["reasons"]


def test_closing_proxy_rejects_old_or_postgame_prices():
    start = datetime.now(UTC)
    q = Quote(
        "a",
        "e",
        "h2h",
        "A",
        "draftkings",
        D(2),
        None,
        start - timedelta(seconds=20),
        start - timedelta(seconds=30),
        DataQuality.REALTIME,
        "nfl",
        "A @ B",
        start,
    )
    qs = (
        q,
        replace(q, selection_key="B", provider_quote_id="b"),
        replace(q, sportsbook="fanduel", provider_quote_id="c"),
        replace(q, sportsbook="fanduel", selection_key="B", provider_quote_id="d"),
    )
    kwargs = {
        "starts_at": start,
        "now": start + timedelta(minutes=1),
        "event_id": "e",
        "market": "h2h",
        "selection": "A",
    }
    assert closing_proxy(qs, **kwargs)["status"] == "CLOSING_PROXY"
    assert closing_proxy(qs, **kwargs)["probability"] == D(".5")
    old = tuple(replace(q, source_timestamp=start - timedelta(minutes=10)) for q in qs)
    assert closing_proxy(old, **kwargs)["status"] == "UNAVAILABLE"
    future = tuple(replace(q, source_timestamp=start + timedelta(seconds=10)) for q in qs)
    assert closing_proxy(future, **kwargs)["status"] == "UNAVAILABLE"

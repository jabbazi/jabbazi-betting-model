from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import pytest
from jabazi.research.backtest import HistoricalDecision, replay


def record(id="a", outcome=1):
    t = datetime(2025, 1, 1, tzinfo=UTC)
    return HistoricalDecision(
        id,
        "nfl",
        "h2h",
        "test-v1",
        t,
        t + timedelta(hours=1),
        t + timedelta(hours=5),
        t,
        t - timedelta(days=1),
        t,
        t,
        D(".6"),
        D(".5"),
        D(2),
        D(10),
        outcome,
        D(100),
        D(".55"),
        t + timedelta(minutes=59),
    )


def test_realized_roi_clv_costs_and_push_accounting():
    records = [record(), record("b", 0), record("c", None)]
    result = replay(records, initial_bankroll=1000, unit_size=30, cost_per_bet=1)
    assert result["summary"]["n"] == 3
    assert result["summary"]["decisive_n"] == 2
    assert result["summary"]["profit"] == -3
    assert result["summary"]["roi"] == D("-.1")
    assert result["summary"]["average_probability_clv"] == D(".05")
    assert result["summary"]["probability_scores"]["brier"] == pytest.approx(0.26)
    assert result["final_bankroll"] == 997


def test_backtest_rejects_unavailable_prices_and_future_features():
    r = record()
    with pytest.raises(ValueError, match="Future"):
        replace(r, features_available_at=r.starts_at)
    with pytest.raises(ValueError, match="Future"):
        replace(r, model_fitted_at=r.starts_at)
    stale = replace(r, odds_source_at=r.decision_at - timedelta(minutes=10))
    result = replay([stale], initial_bankroll=1000, unit_size=30)
    assert result["summary"]["n"] == 0
    assert result["rejected"][0]["reason"] == "STALE_ODDS"


def test_simultaneous_positions_cannot_reuse_cash():
    result = replay([record("a"), record("b")], initial_bankroll=15, unit_size=30)
    assert result["summary"]["n"] == 1
    assert result["rejected"][0]["reason"] == "BANKROLL_UNAVAILABLE"


def test_old_closing_snapshot_is_not_reported_as_clv():
    r = record()
    result = replay([replace(r, closing_at=r.decision_at)], initial_bankroll=1000, unit_size=30)
    assert result["summary"]["clv_n"] == 0

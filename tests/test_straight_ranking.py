"""Exact-line straight-ranking safeguards (isolated, no provider requests)."""
from datetime import UTC, datetime, timedelta

from jabazi.research.straight_ranking import rank_verified_straights


NOW = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)


def offer(**changes):
    row = dict(
        sport="basketball_nba", event_id="event-1", participant="Player A",
        market="player_points", side="over", line="20.5",
        sportsbook="Book A", american_odds=-110,
        model_probability="0.60", push_probability="0",
        observed_at=NOW.isoformat(),
        starts_at=(NOW + timedelta(hours=2)).isoformat(),
        model_version="version-1", model_stage="PRODUCTION_APPROVED",
        approved_for_betting=True, validation_passed=True,
        identity_verified=True, exact_line_verified=True,
        price_is_current=True,
    )
    row.update(changes)
    return row


def test_best_straight_calculates_net_ev_and_price():
    out = rank_verified_straights([offer()], now=NOW)
    assert out["status"] == "QUALIFYING_STRAIGHT"
    assert float(out["best_straight"]["expected_net_return_per_unit"]) > .14
    assert out["betting_enabled"] is False


def test_validating_models_can_never_get_best_straight():
    out = rank_verified_straights([offer(model_stage="VALIDATING")], now=NOW)
    assert out["status"] == "PASS"
    assert out["research_only_rows"] == 1
    assert out["best_straight"] is None


def test_no_fabricated_price_identity_or_stale_quote():
    rows = [
        offer(decimal_odds=None, american_odds=None),
        offer(identity_verified=False),
        offer(observed_at=(NOW - timedelta(hours=1)).isoformat()),
        offer(starts_at=(NOW - timedelta(minutes=1)).isoformat()),
    ]
    out = rank_verified_straights(rows, now=NOW)
    assert out["status"] == "PASS"
    assert sum(out["rejection_counts"].values()) == 4


def test_same_selection_at_different_books_deduplicates_to_best_price():
    out = rank_verified_straights([
        offer(sportsbook="First", american_odds=-110),
        offer(sportsbook="Better", american_odds=110),
    ], now=NOW)
    assert out["qualifying_distinct_selections"] == 1
    assert out["best_straight"]["sportsbook"] == "Better"


def test_push_probability_does_not_count_as_loss():
    out = rank_verified_straights([
        offer(line="20", model_probability="0.51", push_probability="0.10"),
    ], now=NOW)
    assert out["status"] == "QUALIFYING_STRAIGHT"


def test_low_edge_and_bad_probabilities_fail_closed():
    out = rank_verified_straights([
        offer(model_probability="0.30"),
        offer(model_probability="nan"),
        offer(model_probability="0.8", push_probability="0.3"),
        offer(exact_line_verified=False),
    ], now=NOW)
    assert out["status"] == "PASS"
    assert out["best_straight"] is None

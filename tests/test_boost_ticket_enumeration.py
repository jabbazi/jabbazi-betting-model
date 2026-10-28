"""Research ticket enumeration never approves odds or joint probabilities."""
from datetime import datetime, timedelta, timezone

import pytest

from jabazi.boost_ticket_enumeration import (
    BoostLeg, BoostTicketTerms, enumerate_research_tickets,
)

NOW = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)
TERMS = BoostTicketTerms(
    "basketball_nba", "draftkings", 2, 3, frozenset({"g1"}),
    frozenset({"points", "rebounds"}),
)


def leg(identifier, *, player=None, market="points", sport="basketball_nba",
        book="draftkings", quoted_at=None, starts_at=None):
    return BoostLeg(
        identifier, sport, "g1", player or identifier, market, "over", book,
        quoted_at or NOW - timedelta(minutes=1),
        starts_at or NOW + timedelta(hours=1),
    )


def run(legs, terms=TERMS, **options):
    return enumerate_research_tickets(
        legs, terms, observed_at=NOW, feed_coverage="FULL",
        terms_verified=True, promotion_active=True, **options,
    )


def test_enumerates_only_eligible_2_and_3_leg_structures():
    tickets = run([
        leg("a"), leg("b"), leg("c", market="rebounds"),
        leg("other", sport="icehockey_nhl"),
        leg("other-book", book="fanduel"),
        leg("stale", quoted_at=NOW - timedelta(minutes=8)),
        leg("closed", starts_at=NOW - timedelta(minutes=1)),
    ])
    assert tickets == (("a", "b"), ("a", "c"), ("b", "c"), ("a", "b", "c"))


@pytest.mark.parametrize("override", [
    {"feed_coverage": "PARTIAL"},
    {"terms_verified": False},
    {"promotion_active": False},
])
def test_incomplete_evidence_has_no_tickets(override):
    args = dict(observed_at=NOW, feed_coverage="FULL",
                terms_verified=True, promotion_active=True)
    args.update(override)
    assert enumerate_research_tickets(
        [leg("a"), leg("b")], TERMS, **args,
    ) == ()


def test_same_player_market_is_not_double_counted():
    tickets = run([leg("x", player="p1"),
                   leg("y", player="p1"),
                   leg("z", player="p2")])
    assert ("x", "y") not in tickets
    assert ("x", "y", "z") not in tickets


def test_explicit_promo_game_scope_is_enforced():
    assert run([leg("a"), leg("b")],
               BoostTicketTerms(
                   "basketball_nba", "draftkings", 2, 2,
                   frozenset({"other-game"}), frozenset(),
               )) == ()


def test_combination_cap_rejects_partial_enumeration():
    with pytest.raises(ValueError, match="Combination cap"):
        run([leg("a"), leg("b"), leg("c")], maximum_combinations=2)


def test_duplicate_offer_identity_fails_closed():
    with pytest.raises(ValueError, match="Duplicate leg"):
        run([leg("a"), leg("a"), leg("b")])

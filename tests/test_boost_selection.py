from decimal import Decimal as D
from jabazi.boost_selection import BoostCandidate, select_best_boost


def candidate(name, sport="icehockey_nhl", validated=True, price="3"):
    return BoostCandidate(name, sport, ("leg1", "leg2"),
                          D(".4"), D(".35"), D(price), validated, True, True)


def test_best_eligible_candidate_only():
    result = select_best_boost([
        candidate("lower", price="3"),
        candidate("higher", price="4"),
        candidate("unrelated", sport="basketball_nba", price="9"),
    ], sport="icehockey_nhl", boost_fraction=D(".3"), stake=D("25"),
       maximum_stake=D("50"), minimum_decimal_odds=D("2"))
    assert result["candidate"] == "higher"
    assert result["decision"] == "WATCH"
    assert result["evaluated_count"] == 2


def test_no_validated_joint_returns_pass():
    result = select_best_boost([
        candidate("shadow", validated=False)
    ], sport="icehockey_nhl", boost_fraction=D(".3"), stake=D("25"),
       maximum_stake=D("50"), minimum_decimal_odds=D("2"))
    assert result["decision"] == "PASS"
    assert result["candidate"] is None

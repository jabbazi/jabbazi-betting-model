from decimal import Decimal as D
import pytest

from jabazi.domain.pricing import (
    american_probability,
    fair_american,
    book_hold,
    no_vig,
    value,
    roi,
    minimum_decimal,
    dollars,
    units,
    independent_joint,
    scenario_joint,
    frechet_bounds,
    profit_boost,
    bonus_bet_cash_value,
    probability,
)
from jabazi.domain.portfolio import Position, Limits, allocate


@pytest.mark.parametrize("odds,expected", [(100, D(".5")), (-150, D(".6")), (300, D(".25"))])
def test_american_probability_reference(odds, expected):
    assert american_probability(odds) == expected
    assert fair_american(expected) == odds


def test_two_and_three_way_complete_market_no_vig():
    assert all(abs(p - D(".5")) < D("1e-25") for p in no_vig([D("1.91"), D("1.91")]))
    assert abs(book_hold([D("1.91")] * 2) - D(".047120418848167539267015706")) < D("1e-25")
    assert abs(sum(no_vig([D(2), D(3), D(4)])) - 1) < D("1e-25")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "-.1", "1.1", None])
def test_invalid_probabilities_rejected(bad):
    with pytest.raises(ValueError):
        probability(bad)


def test_probability_edge_is_not_expected_roi_and_haircut_is_explicit():
    result = value(".60", ".52", "1.90", stake=30, uncertainty=".02", required_roi=".03")
    assert result.probability_edge == D(".08")
    assert result.adjusted_probability == D(".58")
    assert result.expected_roi == D(".102")
    assert result.expected_profit == D("3.06")
    assert roi(".58", result.minimum_playable_decimal) == D(".03")
    assert result.minimum_playable_decimal > result.fair_decimal


def test_push_is_refunded_and_not_counted_as_loss():
    assert roi(".45", 2, push=".10") == 0
    assert minimum_decimal(".45", push=".10") == 2
    with pytest.raises(ValueError):
        roi(".9", 2, push=".2")
    with pytest.raises(ValueError):
        value(".9", ".5", 2, uncertainty=".3", push=".2")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "not-a-number"])
def test_legacy_math_rejects_nonfinite_inputs(bad):
    from jabazi.domain.odds import expected_value, fractional_kelly, max_playable_decimal

    with pytest.raises(ValueError):
        expected_value(D(".6"), bad)
    with pytest.raises(ValueError):
        fractional_kelly(bad, D(2), D(".1"))
    with pytest.raises(ValueError):
        max_playable_decimal(D(".6"), bad)


@pytest.mark.parametrize(
    "u,cash",
    [
        (".20", "6"),
        (".25", "7.50"),
        (".50", "15"),
        (".75", "22.50"),
        ("1", "30"),
        ("1.5", "45"),
        ("2", "60"),
    ],
)
def test_unit_conversions(u, cash):
    assert dollars(u, 30) == D(cash)
    assert units(cash, 30) == D(u)
    assert dollars(u, 40) == D(u) * 40


def test_joint_probability_retains_shared_scenario_dependence():
    with pytest.raises(ValueError):
        independent_joint([".5", ".5"])
    assert independent_joint([".5", ".5"], independence_confirmed=True) == D(".25")
    assert scenario_joint([(True, True), (False, False)], [D(".5"), D(".5")]) == D(".5")
    assert frechet_bounds([".8", ".7"]) == (D(".5"), D(".7"))
    with pytest.raises(ValueError):
        scenario_joint([(True, False)], [D(".9")])


def test_boost_cap_and_stake_not_returned_bonus_bet():
    assert profit_boost(3, ".5") == 4
    assert profit_boost(3, ".5", profit_cap=5, stake=10) == D("3.5")
    assert bonus_bet_cash_value(".4", 3, 10) == 8


def proposal(**kwargs):
    return Position(
        D(0),
        "nfl",
        "game",
        players=frozenset({"player"}),
        theses=frozenset({"offense"}),
        betting_date="2026-09-22",
        **kwargs,
    )


def test_central_limits_include_other_origins_and_other_days_open_risk():
    positions = [
        Position(
            D(40),
            "nfl",
            "game",
            theses=frozenset({"offense"}),
            origin="user",
            betting_date="2026-09-21",
        )
    ]
    result = allocate(".8", 2, proposal(), positions, Limits(D(1000)))
    assert result.dollars == 0
    assert "thesis:offense" in result.reasons


def test_sizing_respects_tiers_and_drawdown():
    limits = Limits(D(1000))
    assert allocate(".7", 2, proposal(), [], limits).units == D(".50")
    assert allocate(".7", 2, proposal(parlay=True), [], limits, tier="exceptional").units == D(
        ".25"
    )
    assert allocate(".7", 2, proposal(), [], limits, drawdown=".20").dollars == 0
    # Per-bet cap prevents an exceptional label from bypassing bankroll limits.
    assert allocate(".7", 2, proposal(), [], limits, tier="exceptional").dollars <= 20


@pytest.mark.parametrize("scope", ["daily", "sport", "event", "player", "parlays"])
def test_each_exposure_dimension_is_enforced(scope):
    limits = Limits(D(1000), **{scope: D(".01")})
    existing = Position(
        D(10),
        "nfl",
        "game",
        players=frozenset({"player"}),
        theses=frozenset({"different"}),
        parlay=True,
        betting_date="2026-09-22",
    )
    assert allocate(".9", 2, proposal(parlay=True), [existing], limits).dollars == 0

from decimal import Decimal as D
from jabazi.boost_valuation import evaluate_boost


def test_boost_profit_and_conservative_roi():
    v = evaluate_boost(
        joint_probability=D(".35"), conservative_probability=D(".30"),
        offered_decimal=D("3"), boost_fraction=D(".30"),
        stake=D("25"), maximum_stake=D("50"), minimum_decimal_odds=D("2"),
        terms_verified=True, eligible=True, joint_model_validated=True,
    )
    assert v.boosted_decimal == D("3.60")
    assert v.expected_roi == D(".2600")
    assert v.conservative_roi == D(".0800")
    assert v.status == "WATCH"


def test_unvalidated_joint_probability_fails_closed():
    v = evaluate_boost(
        joint_probability=D(".35"), conservative_probability=D(".30"),
        offered_decimal=D("3"), boost_fraction=D(".30"),
        stake=D("25"), maximum_stake=D("50"), minimum_decimal_odds=D("2"),
        terms_verified=True, eligible=True, joint_model_validated=False,
    )
    assert v.status == "PASS"
    assert "JOINT_MODEL_NOT_VALIDATED" in v.reasons


def test_profit_cap_is_respected():
    v = evaluate_boost(
        joint_probability=D(".4"), conservative_probability=D(".3"),
        offered_decimal=D("3"), boost_fraction=D(".5"),
        profit_cap=D("5"), stake=D("25"), maximum_stake=D("25"),
        minimum_decimal_odds=D("2"),
    )
    assert v.boosted_decimal == D("3.2")

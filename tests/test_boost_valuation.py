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


def test_capped_play_to_inverts_actual_payout():
    args = dict(
        joint_probability=D(".4"), conservative_probability=D(".3"),
        boost_fraction=D(".5"), profit_cap=D("5"), stake=D("25"),
        maximum_stake=D("25"), minimum_decimal_odds=D("2"),
        terms_verified=True, eligible=True, joint_model_validated=True)
    result = evaluate_boost(offered_decimal=D("3.2"), **args)
    assert result.minimum_playable_decimal == D("3.2")
    assert result.conservative_roi == D(".02")
    assert result.status == "WATCH"
    assert evaluate_boost(offered_decimal=D("3.199"), **args).status == "PASS"


def test_play_to_respects_promotion_minimum_price():
    result = evaluate_boost(
        joint_probability=D(".8"), conservative_probability=D(".7"),
        offered_decimal=D("2"), boost_fraction=D(".3"), stake=D("25"),
        maximum_stake=D("50"), minimum_decimal_odds=D("3"))
    assert result.minimum_playable_decimal == D("3")
    assert "MINIMUM_ODDS_NOT_MET" in result.reasons


def test_zero_probability_has_no_finite_play_to_price():
    result = evaluate_boost(
        joint_probability=D("0"), conservative_probability=D("0"),
        offered_decimal=D("3"), boost_fraction=D(".3"), stake=D("25"),
        maximum_stake=D("50"), minimum_decimal_odds=D("2"), profit_cap=D("5"))
    assert result.minimum_playable_decimal is None
    assert result.status == "PASS"

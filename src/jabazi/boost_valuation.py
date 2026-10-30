"""Boost pricing on externally validated joint probabilities and exact offers.

No independent multiplication, model promotion, or automatic wagering.
"""
from dataclasses import dataclass
from decimal import Decimal as D

from jabazi.domain.pricing import decimal_price, probability, profit_boost, roi, minimum_decimal


@dataclass(frozen=True)
class BoostValuation:
    status: str
    joint_probability: D
    conservative_probability: D
    offered_decimal: D
    boosted_decimal: D
    expected_roi: D
    conservative_roi: D
    minimum_playable_decimal: D | None
    stake: D
    reasons: tuple[str, ...]


def evaluate_boost(*, joint_probability, conservative_probability, offered_decimal,
                   boost_fraction, stake, maximum_stake, minimum_decimal_odds,
                   terms_verified=False, eligible=False, joint_model_validated=False,
                   profit_cap=None, minimum_conservative_roi=D("0.02")):
    """Value an *exact* sportsbook combined offer; never invent a joint model.

    A positive EV is not actionable until all validation gates pass.
    """
    p = probability(joint_probability)
    lower = probability(conservative_probability)
    if lower > p:
        raise ValueError("Conservative probability cannot exceed model probability")
    d = decimal_price(offered_decimal)
    minimum = decimal_price(minimum_decimal_odds) if D(str(minimum_decimal_odds)) > 1 else D(1)
    stake = D(str(stake))
    cap = D(str(maximum_stake))
    if not stake.is_finite() or not cap.is_finite() or stake <= 0 or cap <= 0:
        raise ValueError("Invalid stake limits")
    boosted = profit_boost(d, boost_fraction, profit_cap=profit_cap, stake=stake)
    reasons = []
    if not terms_verified:
        reasons.append("PROMO_TERMS_UNVERIFIED")
    if not eligible:
        reasons.append("PROMO_ELIGIBILITY_UNVERIFIED")
    if not joint_model_validated:
        reasons.append("JOINT_MODEL_NOT_VALIDATED")
    if d < minimum:
        reasons.append("MINIMUM_ODDS_NOT_MET")
    if stake > cap:
        reasons.append("STAKE_CAP_EXCEEDED")
    expected = roi(p, boosted)
    conservative = roi(lower, boosted)
    threshold = D(str(minimum_conservative_roi))
    if threshold < 0 or not threshold.is_finite():
        raise ValueError("Invalid minimum ROI")
    if conservative < threshold:
        reasons.append("INSUFFICIENT_CONSERVATIVE_EV")
    # Invert the same capped payout function used above; include promo minimum odds.
    boost = D(str(boost_fraction))
    if not boost.is_finite() or boost < 0:
        raise ValueError("Invalid boost")
    required_boosted = minimum_decimal(lower, threshold) if lower > 0 else None
    required_original = None
    if required_boosted is not None:
        required_original = D(1) + (required_boosted - 1) / (1 + boost)
        if profit_cap is not None:
            # Both branches of min((d-1)*boost, cap/stake) must meet the target.
            required_original = max(required_original, required_boosted - D(str(profit_cap)) / stake)
        required_original = max(minimum, required_original)
    return BoostValuation(
        status="WATCH" if not reasons else "PASS",
        joint_probability=p, conservative_probability=lower,
        offered_decimal=d, boosted_decimal=boosted,
        expected_roi=expected, conservative_roi=conservative,
        minimum_playable_decimal=required_original,
        stake=stake, reasons=tuple(reasons),
    )

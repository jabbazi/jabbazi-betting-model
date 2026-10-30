"""Conservative boost candidate selection with explicit joint calibration gates.

A candidate must carry a validated joint probability and exact eligible
combined sportsbook quote. Research-only candidates never become BET NOW.
"""
from dataclasses import dataclass
from decimal import Decimal as D

from jabazi.boost_valuation import evaluate_boost


@dataclass(frozen=True)
class BoostCandidate:
    identifier: str
    sport: str
    legs: tuple[str, ...]
    joint_probability: D
    conservative_probability: D
    combined_decimal: D
    joint_model_validated: bool
    terms_verified: bool
    eligible: bool


def select_best_boost(candidates, *, sport, boost_fraction, stake,
                      maximum_stake, minimum_decimal_odds,
                      profit_cap=None, required_roi=D(".02")):
    """Rank only fully qualified candidate parlays by conservative ROI.

    A lack of calibrated joint probabilities returns PASS, not an estimate
    derived from multiplying marginals.
    """
    evaluated = []
    for candidate in candidates:
        if candidate.sport != sport:
            continue
        if not 2 <= len(candidate.legs) <= 4 or len(set(candidate.legs)) != len(candidate.legs):
            continue
        result = evaluate_boost(
            joint_probability=candidate.joint_probability,
            conservative_probability=candidate.conservative_probability,
            offered_decimal=candidate.combined_decimal,
            boost_fraction=boost_fraction,
            stake=stake,
            maximum_stake=maximum_stake,
            minimum_decimal_odds=minimum_decimal_odds,
            terms_verified=candidate.terms_verified,
            eligible=candidate.eligible,
            joint_model_validated=candidate.joint_model_validated,
            profit_cap=profit_cap,
            minimum_conservative_roi=required_roi,
        )
        evaluated.append((candidate, result))
    qualified = [(c, v) for c, v in evaluated if v.status == "WATCH"]
    if not qualified:
        return {"decision": "PASS", "candidate": None,
                "qualified_count": 0, "evaluated_count": len(evaluated)}
    best, valuation = max(qualified, key=lambda pair: (
        pair[1].conservative_roi, pair[1].expected_roi, pair[0].identifier))
    # Research validation is distinct from sportsbook quote freshness and
    # risk/portfolio approval, so do not label this BET NOW.
    return {"decision": "WATCH", "candidate": best.identifier,
            "qualified_count": len(qualified), "evaluated_count": len(evaluated),
            "boosted_decimal": str(valuation.boosted_decimal),
            "estimated_roi": str(valuation.expected_roi),
            "conservative_roi": str(valuation.conservative_roi)}

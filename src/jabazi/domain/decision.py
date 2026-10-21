from datetime import datetime, timezone
from decimal import Decimal

from .consensus import best_quote, consensus_probability
from .models import Candidate, DataQuality, Decision, Quote, Recommendation
from .odds import expected_value, max_playable_decimal
from .risk import RiskPolicy


def evaluate(
    candidate: Candidate,
    opposing_quotes: tuple[Quote, ...],
    policy: RiskPolicy,
    current_exposure: Decimal,
    now: datetime | None = None,
) -> Recommendation:
    now = now or datetime.now(timezone.utc)
    ids = tuple(sorted(quote.provider_quote_id for quote in candidate.quotes))
    if not candidate.quotes:
        return Recommendation(
            Decision.PASS,
            "no price available",
            None,
            None,
            None,
            candidate.model_probability,
            None,
            Decimal("0"),
            None,
            ids,
        )
    if candidate.uncertainty < 0 or candidate.uncertainty > 1:
        raise ValueError("Uncertainty must be between 0 and 1")
    adjusted = candidate.model_probability * (Decimal("1") - candidate.uncertainty)
    quote = best_quote(candidate.quotes)
    stale = quote.age_seconds(now) > policy.stale_after_seconds
    non_executable = quote.quality in {DataQuality.CACHED, DataQuality.FIXTURE}
    if stale or non_executable:
        reason = "stale price" if stale else f"{quote.quality.value} data is not executable"
        return Recommendation(
            Decision.WAIT,
            reason,
            quote.sportsbook,
            quote.decimal_odds,
            None,
            adjusted,
            None,
            Decimal("0"),
            None,
            ids,
        )
    try:
        market_p = consensus_probability(candidate.quotes, opposing_quotes)
    except ValueError:
        return Recommendation(
            Decision.WATCH,
            "incomplete market; cannot remove vig",
            quote.sportsbook,
            quote.decimal_odds,
            None,
            adjusted,
            None,
            Decimal("0"),
            None,
            ids,
        )
    ev = expected_value(adjusted, quote.decimal_odds)
    threshold = policy.minimum_edge + (current_exposure / policy.bankroll) / Decimal("5")
    playable = max_playable_decimal(adjusted, threshold)
    if not candidate.model_validated:
        return Recommendation(
            Decision.WATCH,
            "model has not passed production validation gates",
            quote.sportsbook,
            quote.decimal_odds,
            market_p,
            adjusted,
            ev,
            Decimal("0"),
            playable,
            ids,
        )
    if ev < threshold:
        return Recommendation(
            Decision.PASS,
            "uncertainty-adjusted EV below threshold",
            quote.sportsbook,
            quote.decimal_odds,
            market_p,
            adjusted,
            ev,
            Decimal("0"),
            playable,
            ids,
        )
    stake = policy.stake(adjusted, quote.decimal_odds, current_exposure)
    if stake <= 0:
        return Recommendation(
            Decision.PASS,
            "daily exposure limit reached",
            quote.sportsbook,
            quote.decimal_odds,
            market_p,
            adjusted,
            ev,
            stake,
            playable,
            ids,
        )
    return Recommendation(
        Decision.BET_NOW,
        "price clears EV and risk thresholds",
        quote.sportsbook,
        quote.decimal_odds,
        market_p,
        adjusted,
        ev,
        stake,
        playable,
        ids,
    )

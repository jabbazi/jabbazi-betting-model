"""Owner-only promo arithmetic. User assumptions never approve a model or wager."""
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .domain.pricing import profit_boost, roi

router = APIRouter()
Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Probability = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]


class PromoRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['early_win_7', 'profit_boost', 'bonus_bet', 'no_sweat', 'bet_and_get']
    book: str = Field(min_length=1, max_length=100)
    event_id: str = Field(min_length=1, max_length=200)
    terms_source: str = Field(min_length=1, max_length=500)
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    starts_at: AwareDatetime
    terms_verified: bool = False
    event_eligible: bool = False
    token_required: bool = True
    token_applied: bool = False
    decimal_odds: Decimal = Field(gt=1, allow_inf_nan=False)
    minimum_decimal_odds: Decimal = Field(ge=1, allow_inf_nan=False)
    stake: Decimal = Field(gt=0, allow_inf_nan=False)
    maximum_stake: Amount
    boost_fraction: Amount = Decimal(0)
    extra_profit_cap: Amount | None = None
    bonus_stake_returned: bool = False
    reward_face_value: Amount | None = None
    reward_type: Literal['cash', 'bonus'] = 'bonus'
    # This is explicitly a hypothetical conversion assumption, not cash face value.
    bonus_conversion_fraction: Probability | None = None
    reward_conditions_verified: bool = False
    assumed_win_probability: Probability | None = None
    assumed_push_probability: Probability = Decimal(0)

    @model_validator(mode='after')
    def coherent(self):
        if self.assumed_win_probability is not None and self.assumed_win_probability + self.assumed_push_probability > 1:
            raise ValueError('Win plus push probability exceeds one')
        return self


def calculate(body: PromoRequest, now: datetime):
    reasons = []
    if not body.terms_verified or not body.event_eligible:
        reasons.append('TERMS_OR_EVENT_UNVERIFIED')
    if body.token_required and not body.token_applied:
        reasons.append('TOKEN_NOT_APPLIED')
    if now >= body.expires_at:
        reasons.append('PROMO_EXPIRED')
    if now >= body.starts_at:
        reasons.append('PREGAME_ONLY')
    if body.observed_at > now or (now - body.observed_at).total_seconds() > 300:
        reasons.append('QUOTE_STALE_OR_FUTURE')
    if body.stake > body.maximum_stake:
        reasons.append('STAKE_CAP_EXCEEDED')
    if body.decimal_odds < body.minimum_decimal_odds:
        reasons.append('MINIMUM_ODDS_NOT_MET')
    d = body.decimal_odds
    if body.kind == 'profit_boost':
        d = profit_boost(d, body.boost_fraction, profit_cap=body.extra_profit_cap, stake=body.stake)
    payout = body.stake * d
    if body.kind == 'bonus_bet' and not body.bonus_stake_returned:
        payout -= body.stake
    output = dict(status='RESEARCH_ONLY', decision='PASS' if reasons else 'WATCH',
                  reasons=reasons, model_status='UNAVAILABLE', model_probability=None,
                  probability_source='USER_SCENARIO_NOT_MODEL', terms=body.model_dump(mode='json'),
                  effective_decimal=d, hypothetical_win_payout=payout,
                  assumed_cash_ev_per_dollar=None, assumed_promo_net_value=None,
                  promo_ev_status='PROMO EV UNAVAILABLE', minimum_acceptable_price=None,
                  official_wager=False)
    p, push = body.assumed_win_probability, body.assumed_push_probability
    if body.kind == 'early_win_7':
        reasons.append('VALIDATED_LEAD_PATH_MODEL_UNAVAILABLE')
        return output
    if p is None:
        reasons.append('PROBABILITY_UNAVAILABLE')
        return output
    if reasons:
        return output
    base = roi(p, body.decimal_odds, push)
    output['assumed_cash_ev_per_dollar'] = base
    if body.kind == 'profit_boost':
        net = body.stake * roi(p, d, push)
    elif body.kind == 'bonus_bet':
        # Bonus stake is not a cash outlay; this is expected cash proceeds.
        if push:
            reasons.append('BONUS_PUSH_SETTLEMENT_UNSUPPORTED')
            return output
        net = p * payout
    else:
        if not body.reward_conditions_verified or body.reward_face_value is None:
            reasons.append('REWARD_CONDITIONS_UNVERIFIED')
            return output
        conversion = Decimal(1) if body.reward_type == 'cash' else body.bonus_conversion_fraction
        if conversion is None:
            reasons.append('BONUS_CONVERSION_UNAVAILABLE')
            return output
        reward = body.reward_face_value * conversion
        if body.kind == 'no_sweat':
            reward = min(body.reward_face_value, body.stake) * conversion * (1 - p - push)
        elif push:
            reasons.append('BET_GET_PUSH_ELIGIBILITY_UNSUPPORTED')
            return output
        net = body.stake * base + reward
    output.update(assumed_promo_net_value=net, promo_ev_status='HYPOTHETICAL_SCENARIO_ONLY')
    return output


@router.post('/v1/chatgpt/promo-calculator', operation_id='calculate_promo_scenario')
def evaluate(body: PromoRequest, authorization: Annotated[str | None, Header()] = None):
    from .chatgpt_api import authorize, PRIVATE_HEADERS
    from .api import _json
    authorize(authorization)
    return JSONResponse(_json(calculate(body, datetime.now(UTC))), headers=PRIVATE_HEADERS)

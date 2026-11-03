from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import pytest
from pydantic import ValidationError
from jabazi.promo_api import PromoRequest, calculate

NOW = datetime(2026, 10, 21, 16, tzinfo=UTC)

def body(**updates):
    data = dict(kind='profit_boost', book='manual', event_id='example', terms_source='user screenshot', observed_at=NOW,
                expires_at=NOW+timedelta(hours=1), starts_at=NOW+timedelta(hours=2), terms_verified=True,
                event_eligible=True, token_applied=True, decimal_odds=3, minimum_decimal_odds=1,
                stake=10, maximum_stake=25, boost_fraction='.5', assumed_win_probability='.4')
    return PromoRequest(**(data | updates))

def test_boost_cash_ev_and_cap():
    out = calculate(body(), NOW)
    assert out['effective_decimal'] == 4
    assert out['assumed_promo_net_value'] == 6
    assert out['decision'] == 'WATCH'
    assert out['model_probability'] is None
    assert calculate(body(extra_profit_cap=2), NOW)['assumed_promo_net_value'] == D('2.8')

def test_early_win_never_uses_final_win_probability():
    out = calculate(body(kind='early_win_7'), NOW)
    assert out['assumed_promo_net_value'] is None
    assert 'VALIDATED_LEAD_PATH_MODEL_UNAVAILABLE' in out['reasons']

def test_bonus_and_refund_not_cash_face_value():
    assert calculate(body(kind='bonus_bet'), NOW)['assumed_promo_net_value'] == 8
    refund = body(kind='no_sweat', reward_conditions_verified=True, reward_face_value=10, bonus_conversion_fraction='.5')
    assert calculate(refund, NOW)['assumed_promo_net_value'] == 5
    assert calculate(body(kind='no_sweat'), NOW)['assumed_promo_net_value'] is None

@pytest.mark.parametrize('updates', [dict(stake=26), dict(token_applied=False), dict(observed_at=NOW-timedelta(minutes=6)), dict(expires_at=NOW), dict(event_eligible=False)])
def test_ineligible_never_gets_ev(updates):
    out = calculate(body(**updates), NOW)
    assert out['decision'] == 'PASS'
    assert out['assumed_promo_net_value'] is None

def test_push_and_invalid_probability():
    assert calculate(body(assumed_push_probability='.1'), NOW)['assumed_promo_net_value'] == 7
    with pytest.raises(ValidationError):
        body(assumed_win_probability='.9', assumed_push_probability='.2')

def test_endpoint_requires_auth():
    from fastapi.testclient import TestClient
    from jabazi.api import app
    assert TestClient(app).post('/v1/chatgpt/promo-calculator', json=body().model_dump(mode='json')).status_code in (401, 403, 503)

def test_bet_get_reward_and_missing_conversion():
    args = dict(kind='bet_and_get', reward_conditions_verified=True, reward_face_value=5)
    assert calculate(body(**args), NOW)['assumed_promo_net_value'] is None
    assert calculate(body(**args, reward_type='cash'), NOW)['assumed_promo_net_value'] == 7
    assert calculate(body(**args, bonus_conversion_fraction='.5'), NOW)['assumed_promo_net_value'] == D('4.5')

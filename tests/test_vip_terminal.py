from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest
from test_member_portal import portal as _portal_fixture
from test_member_portal import sign_in

portal = _portal_fixture
from jabazi.vip import data
from jabazi.vip.auth import _cache, current_access
from jabazi.vip.state import change_watch, check_watches


def seed(store, **changes):
    now = datetime.now(UTC)
    row = {'sport': 'baseball_mlb', 'event_id': 'event-1', 'event': 'Yankees @ Orioles', 'participant': 'Aaron Judge',
           'market': 'batter_home_runs', 'selection': 'Over', 'line': '0.5', 'decimal_odds': '4.0', 'book': 'Test book',
           'research_probability': '.3', 'market_no_vig_probability': '.25', 'model_version': 'test-hr-v1', 'model_stage': 'VALIDATING',
           'status': 'WATCH', 'data_health': 'HEALTHY', 'executable': True, 'price_stale': False,
           'starts_at_utc': (now+timedelta(hours=2)).isoformat(), 'price_time_utc': now.isoformat(), **changes}
    store.append('research_sheet', 'latest_scan', {'rows': [row], 'healthy': True, 'completed_at': now.isoformat()})
    return row


def test_terminal_login_role_revocation_and_no_idor(portal, monkeypatch):
    store, client = portal
    seed(store)
    assert client.get('/v1/vip/home').status_code == 401
    sign_in(store, client)
    assert client.get('/v1/vip/home').status_code == 200
    r = client.get('/v1/vip/board').json()['rows'][0]
    assert r['status'] == 'WATCH' and not r['approved_for_betting']
    assert r['fair_decimal'] == pytest.approx(1/.3)
    assert r['ev'] == pytest.approx(.2)
    assert client.post('/v1/vip/watchlist', json={'candidate_id': r['id']}).status_code == 403
    origin = {'Origin': 'https://jabbazi-research-api.onrender.com'}
    assert client.post('/v1/vip/watchlist', json={'candidate_id': r['id']}, headers=origin).status_code == 200
    assert len(client.get('/v1/vip/watchlist').json()['items']) == 1
    assert client.post('/v1/vip/watchlist', json={'candidate_id': r['id'], 'member': 'another-user'}, headers=origin).status_code == 422
    assert client.get('/v1/vip/admin').status_code == 403
    from jabazi.member_access import issue_ticket
    ticket = issue_ticket(store, guild=1, member=3, authorized=True)
    assert client.post('/v1/member/session', json={'ticket': ticket}, headers=origin).status_code == 200
    assert client.get('/v1/vip/watchlist').json()['items'] == []
    monkeypatch.setattr('jabazi.vip.auth.current_access', lambda *_: {'vip': False, 'admin': False, 'tier': 'FREE'})
    for path in ('home', 'search?q=Judge', 'board', 'watchlist', 'sheets', 'performance', 'models', 'admin'):
        assert client.get('/v1/vip/'+path).status_code == 403
    assert client.get('/v1/member/sheets').status_code == 403
    assert client.post('/v1/member/logout', headers=origin).status_code == 200
    assert client.get('/v1/vip/home').status_code == 401


@pytest.mark.parametrize('changes', [
    {'price_time_utc': 'bad'}, {'price_time_utc': '2099-01-01T00:00:00Z'}, {'starts_at_utc': '2000-01-01T00:00:00Z'},
    {'executable': False}, {'price_stale': True}, {'status': 'QUARANTINED'}, {'data_health': 'UNKNOWN'},
])
def test_top_ten_never_fills_with_unqualified_candidates(portal, changes):
    store, client = portal
    seed(store, model_stage='PRODUCTION_APPROVED', **changes)
    sign_in(store, client)
    assert client.get('/v1/vip/top10?kind=hr').json()['rows'] == []


def test_search_aliases_provenance_and_jurisdiction(portal):
    store, client = portal
    seed(store)
    sign_in(store, client)
    r = client.get('/v1/vip/search?q=Judge%20HR').json()
    assert len(r['rows']) == 1
    assert r['rows'][0]['model_version'] == 'test-hr-v1'
    assert client.get('/v1/vip/top10').json()['rows'] == []
    seed(store, sport='americanfootball_ncaaf', participant='College Player', market='player_pass_yds')
    assert client.get('/v1/vip/board').json()['rows'] == []
    assert client.get('/v1/vip/search?q=College').json()['rows'] == []


def test_watch_alert_crosses_once_and_missing_market_fails_closed(portal):
    store, _ = portal
    seed(store, decimal_odds='3.5')
    b = data.board(store)
    candidate = b['rows'][0]
    change_watch(store, '1:2', candidate, threshold=4)
    check_watches(store, '1:2', b)
    seed(store, decimal_odds='4.1')
    b = data.board(store)
    check_watches(store, '1:2', b)
    check_watches(store, '1:2', b)
    alerts = store.list_records('vip_notification', 20, entity='1:2')
    assert len(alerts) == 1 and alerts[0]['payload']['state'] == 'PRICE TARGET MET'
    check_watches(store, '1:2', {'rows': [], 'snapshot_id': 'removed'})
    assert store.list_records('vip_notification', 1, entity='1:2')[0]['payload']['state'] == 'UNAVAILABLE'


def test_admin_pause_audited_and_reversible_without_history_edit(portal, monkeypatch):
    store, client = portal
    seed(store)
    sign_in(store, client)
    monkeypatch.setattr('jabazi.vip.auth.current_access', lambda *_: {'vip': True, 'admin': True, 'tier': 'ADMIN'})
    origin = {'Origin': 'https://jabbazi-research-api.onrender.com'}
    body = {'key': 'pause_mlb', 'value': True, 'reason': 'Synthetic staging check'}
    assert client.post('/v1/vip/admin/control', json=body, headers=origin).status_code == 200
    assert client.get('/v1/vip/board').json()['rows'][0]['status'] == 'QUARANTINED'
    assert data.paused(store, 'MLB')
    assert len(store.list_records('research_sheet')) == 1
    body['value'] = False
    assert client.post('/v1/vip/admin/control', json=body, headers=origin).status_code == 200
    assert client.get('/v1/vip/board').json()['rows'][0]['status'] == 'WATCH'
    assert len(client.get('/v1/vip/admin').json()['audit']) == 2


def test_discord_role_checks_fail_closed_and_cache_bounded(monkeypatch):
    _cache.clear()
    monkeypatch.setenv('JABBAZI_DISCORD_BOT_TOKEN', 'synthetic')
    monkeypatch.setenv('JABBAZI_DISCORD_OWNER_ID', '2')
    role_ids = ['7']
    def handler(req):
        if req.url.path.endswith('/roles'):
            return httpx.Response(200, json=[{'id': '7', 'name': 'FOUNDING VIP'}])
        return httpx.Response(200, json={'roles': role_ids})
    original = httpx.Client
    monkeypatch.setattr('jabazi.vip.auth.httpx.Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    assert current_access('1', '9')['tier'] == 'VIP'
    role_ids.clear()
    _cache.clear()
    assert current_access('1', '9')['tier'] == 'FREE'
    _cache.clear()
    monkeypatch.setattr('jabazi.vip.auth.httpx.Client', Mock(side_effect=httpx.ConnectError('secret-must-not-leak')))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        current_access('1', '9')
    assert error.value.status_code == 503 and 'secret' not in error.value.detail


def test_frozen_sheet_immutable_and_shared_with_discord(portal):
    from jabazi.discord_daily import freeze_daily_moneyline
    store, client = portal
    row = seed(store, market='h2h', participant=None, selection='Yankees')
    current = store.list_records('research_sheet', 1, entity='latest_scan')[0]
    frozen_id, _ = freeze_daily_moneyline(store, current)
    sign_in(store, client)
    sheet = client.get('/v1/vip/sheets').json()
    assert sheet['id'] == frozen_id and sheet['rows'][0]['decimal'] == 4
    seed(store, market='h2h', participant=None, selection='Yankees', decimal_odds='3.2')
    assert client.get('/v1/vip/sheets').json()['rows'][0]['decimal'] == 4
    changed = client.get('/v1/vip/changes').json()['rows'][0]
    assert changed['before_price'] == 4 and changed['price'] == 3.2
    assert row['model_version'] == sheet['rows'][0]['model_version']


def test_personal_unit_validation_and_promo_math(portal):
    store, client = portal
    sign_in(store, client)
    headers = {'Origin': 'https://jabbazi-research-api.onrender.com'}
    assert client.put('/v1/vip/preferences', json={'unit_size': -30}, headers=headers).status_code == 422
    assert client.put('/v1/vip/preferences', json={'unit_size': 50}, headers=headers).status_code == 200
    assert client.get('/v1/vip/me').json()['preferences']['unit_size'] == 50
    result = client.post('/v1/vip/promo', json={'decimal_odds': 3, 'boost_percent': 30, 'probability': .3}, headers=headers).json()
    assert Decimal(str(result['boosted_decimal'])) == Decimal('3.6')
    assert result['boosted_ev'] == pytest.approx(.08)
    assert result['probability_source'] == 'USER_INPUT_NOT_JABBAZI_MODEL'

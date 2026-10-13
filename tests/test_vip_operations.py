from datetime import UTC, datetime, timedelta

from test_member_portal import portal as _portal_fixture, sign_in

portal = _portal_fixture
from jabazi.vip.operations import health


def test_health_missing_stale_failed_and_secret_redaction(portal, monkeypatch):
    store, client = portal
    now = datetime.now(UTC)
    result = health(store, now)
    assert result['worker']['state'] == 'UNAVAILABLE'
    assert result['scan']['last_successful_at'] is None
    store.append('worker_heartbeat', 'research_worker', {'status': 'RUNNING', 'completed_at': (now-timedelta(minutes=4)).isoformat(), 'secret': 'NEVER_DISPLAY'})
    store.append('scan_run', 'ok', {'healthy': True, 'completed_at': (now-timedelta(minutes=10)).isoformat()})
    store.append('scan_run', 'bad', {'healthy': False, 'completed_at': now.isoformat(), 'errors': ['NEVER_DISPLAY']})
    result = health(store, now)
    assert result['worker']['state'] == 'STALE'
    assert result['scan']['state'] == 'DEGRADED'
    assert result['scan']['error_count'] == 1
    assert result['scan']['last_successful_at'] == (now-timedelta(minutes=10)).isoformat()
    assert 'NEVER_DISPLAY' not in str(result)
    assert client.get('/v1/vip/admin').status_code == 401
    sign_in(store, client)
    assert client.get('/v1/vip/admin').status_code == 403
    monkeypatch.setattr('jabazi.vip.auth.current_access', lambda *_: {'tier':'VIP', 'vip':True, 'admin':True})
    assert client.get('/v1/vip/admin').json()['health'] is None
    monkeypatch.setenv('JABBAZI_DISCORD_OWNER_ID', '2')
    monkeypatch.setenv('RENDER_GIT_COMMIT', 'a'*40)
    result = client.get('/v1/vip/admin')
    assert result.status_code == 200
    assert result.json()['health']['api']['commit'] == 'a'*40
    assert 'NEVER_DISPLAY' not in result.text


def test_future_heartbeat_is_not_healthy(portal):
    store, _ = portal
    now = datetime.now(UTC)
    store.append('worker_heartbeat', 'research_worker', {'status':'RUNNING', 'completed_at':(now+timedelta(hours=1)).isoformat()})
    result = health(store, now)
    assert result['worker']['state'] == 'STALE'
    assert result['worker']['age_seconds'] is None


def test_prop_board_keeps_exact_event_identity(portal):
    from test_vip_terminal import seed
    store, client = portal
    first = seed(store, event_id='doubleheader-1')
    second = {**first, 'event_id':'doubleheader-2'}
    store.append('research_sheet', 'latest_scan', {'healthy':True, 'completed_at':datetime.now(UTC).isoformat(), 'rows':[first,second]})
    sign_in(store, client)
    body = client.get('/v1/vip/board?sport=MLB&family=props&event_id=doubleheader-2').json()
    assert body['total'] == 1
    assert body['rows'][0]['event_id'] == 'doubleheader-2'


def test_recap_separates_pending_and_excludes_member_and_reserved():
    from jabazi.performance import official_periods
    now = datetime(2026, 10, 13, 18, tzinfo=UTC)
    base = {'origin':'scanner', 'stake':'30', 'unit_size':'30', 'betting_date':'2026-10-13'}
    rows = [{'id':'loss', 'state':'settled', 'payload':base},
            {'id':'pending', 'state':'placed', 'payload':base},
            {'id':'reservation', 'state':'reserved', 'payload':base},
            {'id':'member', 'state':'placed', 'payload':{**base, 'origin':'member'}}]
    totals = official_periods(rows, {'loss':{'result':'loss','profit':'-30'}}, now)[0]['groups'][0]
    assert totals['losses'] == 1 and totals['unsettled'] == 1
    assert totals['unsettled_stake'] == 30
    assert totals['settled_returns'] == 0 and totals['roi'] == -1


def test_operations_never_loads_complete_scan_payload(portal, monkeypatch):
    store, _ = portal
    store.append('scan_run', 'large', {'healthy':True, 'completed_at':datetime.now(UTC).isoformat(), 'coverage':'x'*1000000})
    monkeypatch.setattr(store, 'list_records', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Full payload read forbidden')))
    assert health(store)['scan']['state'] == 'CURRENT'

import json
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.config import Settings
from jabazi.providers.balldontlie import BallDontLieError, BallDontLieProvider, provider_status


def test_key_only_in_header_and_trimmed():
    seen = []
    def reply(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [], "meta": {}})
    p = BallDontLieProvider(' secret-value\n', transport=httpx.MockTransport(reply), interval=0)
    try:
        p.fetch('nba', 'stats', [('per_page', 1)])
    finally:
        p.close()
    assert seen[0].headers['Authorization'] == 'secret-value'
    assert str(seen[0].url) == 'https://api.balldontlie.io/nba/v1/stats?per_page=1'


@pytest.mark.parametrize('code', [301, 401, 403, 429, 500])
def test_errors_never_expose_body_or_follow_redirects(code):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(code, text='secret-value', headers={'Location': 'https://evil.invalid/'})
    p = BallDontLieProvider('secret-value', transport=httpx.MockTransport(reply), interval=0)
    with pytest.raises(BallDontLieError, match=f'^HTTP_{code}$'):
        p.fetch('nfl', 'stats')
    p.close()
    assert len(calls) == 1


def test_budget_and_missing_key_do_not_request():
    def unexpected(request):
        pytest.fail('unexpected request')
    for key, budget, error in [('', 1, 'MISSING_KEY'), ('secret', 0, 'REQUEST_BUDGET_EXHAUSTED')]:
        p = BallDontLieProvider(key, budget=budget, transport=httpx.MockTransport(unexpected))
        with pytest.raises(BallDontLieError, match=error):
            p.fetch('nba', 'stats')
        p.close()


@pytest.mark.parametrize('payload', [{}, {'data': {}}, {'data': [1]}, {'data': [], 'meta': []}])
def test_rejects_malformed_data(payload):
    p = BallDontLieProvider('secret', transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    with pytest.raises(BallDontLieError, match='INVALID_SCHEMA'):
        p.fetch('nba', 'stats')
    p.close()


def test_capture_retains_provenance_partiality_and_separate_sport_access():
    requests = []
    def reply(request):
        requests.append(request)
        if request.url.path == '/nfl/v1/stats':
            return httpx.Response(401, text='secret')
        if request.url.path.endswith('/games'):
            return httpx.Response(200, json={'data': [{'id': 123}], 'meta': {}})
        return httpx.Response(200, json={'data': [{'id': 2}], 'meta': {'next_cursor': 3}})
    store = Mock()
    p = BallDontLieProvider('secret', transport=httpx.MockTransport(reply), interval=0)
    report = p.capture(store, now=datetime(2026, 10, 25, 4, tzinfo=UTC))
    p.close()
    assert len(requests) == 10
    assert report['sports']['nfl']['stats']['error'] == 'HTTP_401'
    assert report['sports']['nba']['stats']['rows'] == 1
    assert report['sports']['nba']['stats']['has_more']
    assert not report['model_features_enabled']
    assert 'secret' not in json.dumps(report)
    assert store.append.call_count == 9
    assert requests[1].url.params.get_list('dates[]') == ['2026-10-24', '2026-10-25']
    assert requests[4].url.path == '/nba/v2/odds/player_props'
    assert requests[4].url.params['game_id'] == '123'
    snapshot = store.append.call_args.args[2]
    assert snapshot['observed_at'] and snapshot['sha256'] and snapshot['research_only']


def test_rate_limit_stops_capture():
    transport = httpx.MockTransport(lambda r: httpx.Response(429))
    p = BallDontLieProvider('secret', transport=transport, interval=0)
    report = p.capture(Mock())
    p.close()
    assert report['rate_limited']
    assert len(report['sports']) == 1
    assert len(report['sports']['nba']) == 1


def test_missing_key_and_unchecked_status_are_not_success():
    store = Mock()
    store.list_records.return_value = []
    assert provider_status(store, '')['latest_capture'] is None
    p = BallDontLieProvider('', transport=httpx.MockTransport(lambda r: pytest.fail('unexpected request')))
    assert not p.capture(store)['configured']
    p.close()
    store.append.assert_not_called()


def test_env_setting_is_not_in_repr(monkeypatch):
    monkeypatch.setenv('JABBAZI_BALLDONTLIE_API_KEY', ' secret-value\n')
    settings = Settings.from_environment()
    assert settings.balldontlie_api_key == 'secret-value'
    assert 'secret-value' not in repr(settings)


def test_endpoints_require_owner_auth(monkeypatch):
    monkeypatch.setenv('JABBAZI_MODEL_TOKEN', 'x' * 32)
    client = TestClient(app)
    for path in ['/v1/providers/balldontlie', '/v1/providers/balldontlie/snapshots?sport=nba&resource=props']:
        assert client.get(path).status_code == 401


def test_capture_persists_and_deduplicates_across_services(tmp_path, monkeypatch):
    from jabazi.persistence.store import Store
    from jabazi.providers import balldontlie as bdl
    url = 'sqlite:///' + str(tmp_path / 'provider.db')
    store = Store(url, initialize=True)
    report = {'diagnostic_version': 2, 'observed_at': datetime.now(UTC).isoformat(), 'sports': {'nba': {'authentication': {'status': 'AVAILABLE'}}}, 'research_only': True}
    fake = Mock()
    fake.capture.return_value = report
    factory = Mock(return_value=fake)
    monkeypatch.setattr(bdl, 'BallDontLieProvider', factory)
    bdl.capture_once(url, 'secret')
    bdl.capture_once(url, 'secret')
    assert factory.call_count == 1
    assert store.list_records('balldontlie_status', 1)[0]['payload'] == report
    assert store.acquire_lease('balldontlie-capture', 'next-worker', ttl=30)
    store.close()


def test_other_service_lease_prevents_duplicate_requests(tmp_path, monkeypatch):
    from jabazi.persistence.store import Store
    from jabazi.providers import balldontlie as bdl
    url = 'sqlite:///' + str(tmp_path / 'provider.db')
    store = Store(url, initialize=True)
    assert store.acquire_lease('balldontlie-capture', 'other-service', ttl=600)
    factory = Mock()
    monkeypatch.setattr(bdl, 'BallDontLieProvider', factory)
    bdl.capture_once(url, 'secret')
    factory.assert_not_called()
    assert not store.acquire_lease('balldontlie-capture', 'third-service', ttl=30)
    store.close()


def test_free_auth_failure_skips_paid_probes():
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(401)
    p = BallDontLieProvider('secret', transport=httpx.MockTransport(reply), interval=0)
    report = p.capture(Mock())
    p.close()
    assert len(requests) == 2
    assert requests[0].url.path == '/nba/v1/teams'
    assert requests[1].url.path == '/nfl/v1/teams'
    for sport in ('nba', 'nfl'):
        assert report['sports'][sport]['authentication']['error'] == 'HTTP_401'
        assert 'stats' not in report['sports'][sport]


def test_failed_capture_can_retry_after_credential_redeploy(tmp_path, monkeypatch):
    from jabazi.persistence.store import Store
    from jabazi.providers import balldontlie as bdl
    url = 'sqlite:///' + str(tmp_path / 'provider.db')
    store = Store(url, initialize=True)
    failed = {'diagnostic_version': 2, 'observed_at': datetime.now(UTC).isoformat(),
              'sports': {'nba': {'authentication': {'error': 'HTTP_401'}}}}
    store.append('balldontlie_status', 'nba-nfl', failed)
    fake = Mock()
    fake.capture.return_value = {**failed, 'observed_at': datetime.now(UTC).isoformat()}
    factory = Mock(return_value=fake)
    monkeypatch.setattr(bdl, 'BallDontLieProvider', factory)
    bdl.capture_once(url, 'replacement-secret')
    factory.assert_called_once_with('replacement-secret')
    store.close()

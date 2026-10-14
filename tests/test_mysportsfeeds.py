"""Synthetic transport tests only; these do not validate real provider coverage."""
import base64
import json
from datetime import date

import httpx
import pytest

from jabazi.providers.mysportsfeeds import MSFClient, MSFConfig, ProviderUnavailable, main

DAY = date(2026, 10, 14)


def client_for(handler, **kwargs):
    return MSFClient(MSFConfig('synthetic-secret', True),
                     transport=httpx.MockTransport(handler), **kwargs)


@pytest.mark.parametrize('config,reason', [(MSFConfig(), 'DISABLED'),
                                          (MSFConfig('', True), 'AWAITING_CREDENTIAL')])
def test_no_requests_when_disabled_or_missing_key(config, reason):
    client = MSFClient(config, transport=httpx.MockTransport(lambda r: pytest.fail('network')))
    with pytest.raises(ProviderUnavailable, match=reason):
        client.fetch('nfl', '2026-regular', 'games', day=DAY)
    assert client.requests == 0


def test_auth_only_in_header_and_receipt_is_not_validation():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'games': []})
    client = client_for(handler)
    receipt = client.fetch('nfl', '2026-regular', 'games', day=DAY)
    assert str(requests[0].url) == 'https://api.mysportsfeeds.com/v2.1/pull/nfl/2026-regular/date/20261014/games.json'
    token = base64.b64encode(b'synthetic-secret:MYSPORTSFEEDS').decode()
    assert requests[0].headers['authorization'] == 'Basic ' + token
    assert 'synthetic-secret' not in str(requests[0].url)
    assert 'synthetic-secret' not in repr(client.config)
    assert 'games' not in repr(receipt).split('retrieved_at=')[-1]
    assert not receipt.metadata()['model_approved']
    assert not receipt.metadata()['schema_verified']
    assert receipt.metadata()['status'] == 'UNVERIFIED_PROVIDER_RESPONSE'


def test_cache_separates_dates_leagues_and_expired_data():
    clock = [0]
    client = client_for(lambda r: httpx.Response(200, json={'games': []}), clock=lambda: clock[0])
    original = client.fetch('nfl', '2026-regular', 'games', day=DAY)
    assert client.fetch('nfl', '2026-regular', 'games', day=DAY) is original
    client.fetch('nfl', '2026-regular', 'games', day=date(2026,10,15))
    client.fetch('nba', '2026-2027-regular', 'games', day=DAY)
    assert client.requests == 3
    clock[0] = 301
    assert client.fetch('nfl', '2026-regular', 'games', day=DAY) is not original
    assert client.requests == 4


@pytest.mark.parametrize('status,code', [(401,'AUTHENTICATION_FAILED'), (403,'FEED_ACCESS_DENIED'),
    (429,'RATE_LIMITED'), (204,'NO_DATA'), (304,'NOT_MODIFIED_WITHOUT_FRESH_CACHE'), (302,'HTTP_302')])
def test_failures_are_sanitized_no_redirect_or_auth_retry(status, code):
    client = client_for(lambda r: httpx.Response(status, text='synthetic-secret',
                                                headers={'Location':'https://other.example/'}))
    with pytest.raises(ProviderUnavailable, match=code) as error:
        client.fetch('nfl', '2026-regular', 'games', day=DAY)
    assert client.requests == 1
    assert 'synthetic-secret' not in str(error.value)


def test_transient_retry_and_batch_budget_are_bounded(monkeypatch):
    monkeypatch.setattr('jabazi.providers.mysportsfeeds.time.sleep', lambda _: None)
    client = client_for(lambda r: httpx.Response(503, text='private provider body'))
    for _ in range(3):
        with pytest.raises(ProviderUnavailable, match='HTTP_503'):
            client.fetch('nfl', '2026-regular', 'games', day=DAY)
    with pytest.raises(ProviderUnavailable, match='BATCH_REQUEST_LIMIT'):
        client.fetch('nfl', '2026-regular', 'games', day=DAY)
    assert client.requests == 6


def test_network_failure_does_not_expose_exception(monkeypatch):
    monkeypatch.setattr('jabazi.providers.mysportsfeeds.time.sleep', lambda _: None)
    def handler(request):
        raise httpx.ReadTimeout('synthetic-secret', request=request)
    client = client_for(handler)
    with pytest.raises(ProviderUnavailable, match='PROVIDER_NETWORK_UNAVAILABLE') as error:
        client.fetch('nfl', '2026-regular', 'games', day=DAY)
    assert client.requests == 2
    assert 'synthetic-secret' not in str(error.value)


@pytest.mark.parametrize('league,season,feed,kwargs', [
    ('mlb','2026-regular','games',{'day':DAY}),
    ('nfl','../../other','games',{'day':DAY}),
    ('nfl','2026-regular','odds',{'day':DAY}),
    ('nfl','2026-regular','games',{}),
    ('nfl','2026-regular','lineup',{'game':'../../other'}),
])
def test_rejects_unsubscribed_sports_and_arbitrary_paths(league, season, feed, kwargs):
    client = client_for(lambda r: pytest.fail('network'))
    with pytest.raises(ProviderUnavailable):
        client.fetch(league, season, feed, **kwargs)
    assert client.requests == 0


@pytest.mark.parametrize('body', [b'not-json', b'[]', b'{"games":NaN}'])
def test_invalid_payload_not_cached(body):
    client = client_for(lambda r: httpx.Response(200, content=body))
    with pytest.raises(ProviderUnavailable, match='INVALID_JSON_OBJECT'):
        client.fetch('nfl', '2026-regular', 'games', day=DAY)
    assert not client._cache


def test_response_size_is_bounded():
    client = client_for(lambda r: httpx.Response(200, content=b'x'*100))
    client.max_bytes = 20
    with pytest.raises(ProviderUnavailable, match='RESPONSE_TOO_LARGE'):
        client.fetch('nfl', '2026-regular', 'games', day=DAY)


def test_default_cli_is_offline_even_with_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('JABBAZI_MSF_API_KEY','synthetic-secret')
    monkeypatch.setenv('JABBAZI_MSF_ENABLED','true')
    monkeypatch.setattr('httpx.Client', lambda **kw: pytest.fail('network'))
    assert main([]) == 0
    output = capsys.readouterr().out
    assert 'synthetic-secret' not in output
    status = json.loads(output)
    assert status['status'] == 'READY_FOR_CONNECTIVITY_TEST'
    assert status['automatic_ingestion_enabled'] is False
    assert status['model_approved'] is False


def test_details_routes_do_not_imply_details_entitlement():
    urls = []
    client = client_for(lambda r: (urls.append(str(r.url)) or httpx.Response(200,json={})))
    for feed in ('boxscore','lineup','playbyplay'):
        receipt = client.fetch('nba','2026-2027-regular',feed,game='12345')
        assert not receipt.metadata()['schema_verified']
    assert all('/nba/2026-2027-regular/games/12345/' in url for url in urls)

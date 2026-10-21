import io
import json
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError
import pytest
from jabazi.persistence.store import Store
from jabazi.providers.odds_transport import request, ProviderUnavailable
from jabazi.providers.errors import error_details

NOW = datetime(2026, 10, 21, 16, tzinfo=UTC)
URL = 'https://api.the-odds-api.com/v4/sports/?apiKey=secret-key'


def test_quota_failure_is_safe_persistent_and_shared_across_sports(tmp_path):
    db = 'sqlite:///' + str(tmp_path / 'circuit.db')
    store = Store(db, initialize=True)
    calls = []
    def fail(url, **kwargs):
        calls.append(url)
        raise HTTPError(url, 401, 'secret-key', {}, io.BytesIO(json.dumps({'error_code': 'OUT_OF_USAGE_CREDITS', 'message': 'secret-key'}).encode()))
    with pytest.raises(ProviderUnavailable) as caught:
        request(URL, store=store, now=NOW, opener=fail)
    assert error_details(caught.value)['provider_code'] == 'OUT_OF_USAGE_CREDITS'
    assert 'secret-key' not in str(caught.value)
    assert 'secret-key' not in str(store.list_records('provider_circuit', 1))
    store.close()
    store = Store(db)
    with pytest.raises(ProviderUnavailable):
        request(URL.replace('/sports/', '/sports/basketball_nba/events'), store=store, now=NOW+timedelta(minutes=5), opener=fail)
    assert len(calls) == 1
    store.close()


def test_rate_limit_honors_bounded_retry_and_recovers():
    store = Store('sqlite:///:memory:', initialize=True)
    def fail(url, **kwargs):
        raise HTTPError(url, 429, 'limited', {'Retry-After': '120'}, io.BytesIO(b'{}'))
    with pytest.raises(ProviderUnavailable) as caught:
        request(URL, store=store, now=NOW, opener=fail)
    assert caught.value.details['retry_at'] == (NOW+timedelta(seconds=120)).isoformat()
    class Response:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n): return b'[]'
    assert request(URL, store=store, now=NOW+timedelta(seconds=121), opener=lambda *a, **k: Response())[0] == b'[]'
    assert store.list_records('provider_circuit', 1)[0]['payload']['status'] == 'HEALTHY'
    store.close()


def test_unknown_provider_body_not_exposed_and_rotated_key_can_probe():
    store = Store('sqlite:///:memory:', initialize=True)
    calls = []
    def fail(url, **kwargs):
        calls.append(url)
        raise HTTPError(url, 401, 'secret', {}, io.BytesIO(b'{"error_code":"secret"}'))
    for url in (URL, URL.replace('secret-key', 'new-key')):
        with pytest.raises(ProviderUnavailable) as caught:
            request(url, store=store, now=NOW, opener=fail)
        assert 'provider_code' not in caught.value.details
    assert len(calls) == 2
    store.close()

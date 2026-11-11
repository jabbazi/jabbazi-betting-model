"""Synthetic transport contracts, not real quote receipts."""
from copy import deepcopy
import json

import httpx
import pytest

from jabazi.providers.opticodds_sgp import request_draftkings_quote, QuoteUnavailable


ENTRIES = [{'fixture_id': 'synthetic-game', 'market': 'Player Goals', 'name': 'Fixture Over 0.5'},
           {'fixture_id': 'synthetic-game', 'market': 'Player Shots On Goal', 'name': 'Fixture Over 2.5'}]


def response():
    return {'data': {'DraftKings': {'error': None, 'missing_entries': None,
        'legs': [dict(e, price=110) for e in ENTRIES], 'price': 440}}}


def test_exact_request_does_not_substitute_book_points_or_prices():
    def transport(request):
        assert request.headers['X-Api-Key'] == 'synthetic-secret'
        assert 'synthetic-secret' not in str(request.url)
        assert json.loads(request.content) == {'sportsbooks': ['DraftKings'], 'entries': ENTRIES}
        assert request.url.params['allow_missing_entries'] == 'false'
        assert request.url.params['allow_sgp_points_mismatch'] == 'false'
        return httpx.Response(200, json=response())
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        receipt = request_draftkings_quote(http, 'synthetic-secret', ENTRIES)
    assert receipt['combined_decimal'] == 5.4
    assert not receipt['calibration_eligible'] and not receipt['forecast_binding_verified']
    assert len(receipt['raw_response_sha256']) == 64
    assert 'synthetic-secret' not in str(receipt)


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'line', 'fixture', 'other_book', 'ai', 'error', 'nan', 'boolean'])
def test_inexact_or_invalid_response_is_rejected(mutation):
    payload = response()
    q = payload['data']['DraftKings']
    if mutation == 'missing': q['missing_entries'] = [ENTRIES[0]]
    if mutation == 'extra': q['legs'].append(dict(ENTRIES[0], price=100))
    if mutation == 'line': q['legs'][0]['name'] = 'Fixture Over 1.5'
    if mutation == 'fixture': q['legs'][0]['fixture_id'] = 'other-game'
    if mutation == 'other_book': payload['data'] = {'FanDuel': q}
    if mutation == 'ai': payload['data'] = {'OpticOdds AI': q}
    if mutation == 'error': q['error'] = 'PRIVATE UPSTREAM ERROR'
    if mutation == 'nan': q['price'] = 'NaN'
    if mutation == 'boolean': q['price'] = True
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        with pytest.raises(QuoteUnavailable) as error:
            request_draftkings_quote(http, 'synthetic-secret', ENTRIES)
    assert 'PRIVATE' not in str(error.value)


def test_missing_access_and_unverified_entry_overrides_make_no_request():
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail('No request'))) as http:
        with pytest.raises(QuoteUnavailable, match='NOT_CONFIGURED'):
            request_draftkings_quote(http, '', ENTRIES)
        wrong = deepcopy(ENTRIES)
        wrong[0]['price_american'] = 100
        with pytest.raises(QuoteUnavailable):
            request_draftkings_quote(http, 'synthetic-secret', wrong)


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
def test_no_redirect_or_retry_and_no_secret_error_leak(status):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(status, text='PRIVATE', headers={'location': 'https://example.test'})
    with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=True) as http:
        with pytest.raises(QuoteUnavailable, match='QUOTE_HTTP_' + str(status)):
            request_draftkings_quote(http, 'synthetic-secret', ENTRIES)
    assert len(calls) == 1


def test_oversize_response_rejected():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x'*1_000_001))) as http:
        with pytest.raises(QuoteUnavailable, match='TOO_LARGE'):
            request_draftkings_quote(http, 'synthetic-secret', ENTRIES)

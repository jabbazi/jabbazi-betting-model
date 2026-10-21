from urllib.error import HTTPError
import httpx
from jabazi.providers.errors import error_details


def test_provider_error_diagnostics_do_not_leak_credentials():
    error = HTTPError('https://example.com?apiKey=secret', 401, 'secret', {}, None)
    details = error_details(error)
    assert details['http_status'] == 401
    assert details['reason'] == 'PROVIDER_AUTHENTICATION_OR_QUOTA'
    assert 'secret' not in str(details)


def test_httpx_status_and_generic_error_are_safe():
    request = httpx.Request('GET', 'https://example.com?token=secret')
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError('secret', request=request, response=response)
    assert error_details(error)['reason'] == 'PROVIDER_RATE_LIMITED'
    assert error_details(ValueError('secret')) == {'error_type': 'ValueError'}

"""Bounded odds transport with durable credential-scoped failure backoff."""
import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

CODES = frozenset({
    'INVALID_KEY', 'DEACTIVATED_KEY', 'EXCEEDED_FREQ_LIMIT', 'MISSING_KEY', 'OUT_OF_USAGE_CREDITS', 'ACCESS_DENIED',
    'RATE_LIMIT_EXCEEDED', 'INVALID_MARKET', 'INVALID_REGION', 'INVALID_BOOKMAKERS',
    'INVALID_SPORT', 'UNKNOWN_SPORT', 'NO_ACCESS',
})


class ProviderUnavailable(RuntimeError):
    def __init__(self, details):
        self.details = details
        super().__init__(details.get('reason', 'PROVIDER_UNAVAILABLE'))


def request(url, *, store=None, now=None, opener=None):
    """One request per invocation; retries happen only after the persisted deadline."""
    now = now or datetime.now(UTC)
    opener = opener or urllib.request.urlopen
    key = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get('apiKey', [''])[0]
    entity = 'odds:' + hashlib.sha256(key.encode()).hexdigest()[:24]
    previous = store.list_records('provider_circuit', 1, entity=entity) if store else []
    prior = previous[0]['payload'] if previous else {}
    retry_at = prior.get('retry_at')
    if retry_at and now < datetime.fromisoformat(retry_at):
        raise ProviderUnavailable(prior)
    try:
        with opener(url, timeout=20) as response:
            raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise ValueError('Odds provider response exceeds size limit')
            result = raw, dict(response.headers.items())
    except (urllib.error.URLError, TimeoutError) as exc:
        from .errors import error_details
        details = error_details(exc)
        code = None
        if isinstance(exc, urllib.error.HTTPError):
            try:
                payload = json.loads(exc.read(8192))
                candidate = payload.get('error_code') if isinstance(payload, dict) else None
                code = candidate if candidate in CODES else None
            except (ValueError, OSError, TypeError):
                pass
        if code:
            details['provider_code'] = code
            details['reason'] = code
        failures = min(int(prior.get('failures', 0)) + 1, 6)
        status = details.get('http_status')
        delay = 3600 if code == 'OUT_OF_USAGE_CREDITS' else 900 if status in (401, 403) else min(30 * 2 ** (failures-1), 900)
        if status == 429 or code == 'EXCEEDED_FREQ_LIMIT':
            try:
                delay = max(60, min(3600, int(exc.headers.get('Retry-After', '60'))))
            except (ValueError, TypeError, AttributeError):
                delay = 60
        details.update(failures=failures, retry_at=(now + timedelta(seconds=delay)).isoformat(), observed_at=now.isoformat())
        logging.getLogger(__name__).warning("ODDS_PROVIDER_FAILURE %s", json.dumps(details, sort_keys=True))
        if store:
            store.append('provider_circuit', entity, details)
        # Never retain the original exception: its URL can contain credentials.
        raise ProviderUnavailable(details) from None
    if store:
        headers = {k.lower(): v for k, v in result[1].items()}
        usage = {}
        for name in ('x-requests-remaining', 'x-requests-used', 'x-requests-last'):
            try:
                value = int(headers[name])
                if value >= 0:
                    usage[name] = value
            except (KeyError, ValueError, TypeError):
                pass
        if usage:
            store.append('provider_usage', entity, {'observed_at': now.isoformat(), **usage})
    if store and prior:
        store.append('provider_circuit', entity, {'status': 'HEALTHY', 'failures': 0, 'observed_at': now.isoformat()})
    return result


def transport(url):
    database = os.getenv('JABBAZI_PLATFORM_DATABASE_URL')
    if not database:
        return request(url)
    from jabazi.persistence.store import Store
    store = Store(database, shared=database.startswith(('postgres:', 'postgresql:', 'postgresql+psycopg:')))
    try:
        return request(url, store=store)
    finally:
        store.close()

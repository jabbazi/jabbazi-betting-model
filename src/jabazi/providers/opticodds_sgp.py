"""Explicit DraftKings SGP observations via OpticOdds; never wager execution.

Callers must independently bind provider fixture/selection identities to a frozen
forecast. This adapter does not approve that binding or attach calibration proof.
"""
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
import json
import math

ENDPOINT = 'https://api.opticodds.com/api/v3/parlay/odds'
FIELDS = ('fixture_id', 'market', 'name')


class QuoteUnavailable(ValueError):
    """Allowlisted error codes only; do not expose credential-bearing responses."""


def _entries(entries):
    if not isinstance(entries, list) or not 2 <= len(entries) <= 4:
        raise QuoteUnavailable('EXACT_TWO_TO_FOUR_ENTRIES_REQUIRED')
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != set(FIELDS):
            raise QuoteUnavailable('EXPLICIT_PROVIDER_SELECTIONS_REQUIRED')
        if any(not isinstance(entry[k], str) or not entry[k].strip()
               or len(entry[k]) > 200 or any(ord(c) < 32 for c in entry[k]) for k in FIELDS):
            raise QuoteUnavailable('INVALID_SELECTION_IDENTITY')
        result.append({k: entry[k] for k in FIELDS})
    identities = [tuple(e[k] for k in FIELDS) for e in result]
    if len(set(identities)) != len(identities) or len({e['fixture_id'] for e in result}) != 1:
        raise QuoteUnavailable('UNIQUE_SAME_GAME_SELECTIONS_REQUIRED')
    return result


def _american(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) < 100:
        raise QuoteUnavailable('INVALID_AMERICAN_PRICE')
    return 1 + value / 100 if value > 0 else 1 + 100 / -value


def request_draftkings_quote(http, api_key, entries):
    """One bounded request, no redirects/retries or fallback books/AI prices."""
    requested = _entries(entries)
    if not isinstance(api_key, str) or not api_key.strip():
        raise QuoteUnavailable('OPTICODDS_ACCESS_NOT_CONFIGURED')
    body = {'sportsbooks': ['DraftKings'], 'entries': requested}
    params = {'odds_format': 'AMERICAN', 'allow_missing_entries': 'false',
              'allow_sgp_points_mismatch': 'false'}
    try:
        with http.stream('POST', ENDPOINT, headers={'X-Api-Key': api_key},
                         params=params, json=body, timeout=15, follow_redirects=False) as response:
            if response.status_code != 200:
                raise QuoteUnavailable('QUOTE_HTTP_' + str(response.status_code))
            chunks, size = [], 0
            for chunk in response.iter_bytes(65536):
                size += len(chunk)
                if size > 1_000_000:
                    raise QuoteUnavailable('QUOTE_RESPONSE_TOO_LARGE')
                chunks.append(chunk)
            raw = b''.join(chunks)
        document = json.loads(raw)
    except QuoteUnavailable:
        raise
    except Exception:
        raise QuoteUnavailable('QUOTE_REQUEST_FAILED') from None
    try:
        quoted = document['data']['DraftKings']
        if quoted.get('error') or quoted.get('missing_entries'):
            raise QuoteUnavailable('EXACT_COMBINATION_UNAVAILABLE')
        legs = quoted['legs']
        actual = Counter(tuple(e[k] for k in FIELDS) for e in legs)
        expected = Counter(tuple(e[k] for k in FIELDS) for e in requested)
        if actual != expected:
            raise QuoteUnavailable('RETURNED_LEGS_DO_NOT_MATCH')
        for leg in legs:
            _american(leg['price'])
        decimal = _american(quoted['price'])
    except QuoteUnavailable:
        raise
    except (KeyError, TypeError, ValueError):
        raise QuoteUnavailable('INVALID_QUOTE_RESPONSE') from None
    return {'provider': 'OpticOdds', 'book': 'DraftKings',
            'observed_at': datetime.now(UTC).isoformat(), 'entries': requested,
            'combined_american': quoted['price'], 'combined_decimal': decimal,
            'raw_response_sha256': sha256(raw).hexdigest(), 'raw_response': document,
            'research_only': True, 'forecast_binding_verified': False,
            'calibration_eligible': False, 'wager_placed': False}

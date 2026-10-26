"""Provider availability is not a full-slate, calibrated or executable prop."""
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.providers.balldontlie import verification_summary

NOW = datetime(2026, 10, 26, 20, tzinfo=UTC)


def sample(now=NOW):
    checks = {name: {'status': 'AVAILABLE', 'rows': 3}
              for name in ('authentication', 'games', 'stats', 'injuries', 'props')}
    return {'observed_at': now.isoformat(), 'sports': {'nba': checks, 'nfl': checks},
            'model_features_enabled': False, 'research_only': True}


def test_sample_success_is_not_a_verified_live_model():
    result = verification_summary(sample(), now=NOW)
    assert result['fresh']
    for sport in ('NBA', 'NFL'):
        item = result['sports'][sport]
        assert item['status'] == 'SAMPLE_ACCESS_CONFIRMED'
        assert item['sample_only']
        assert not item['full_slate_coverage_verified']
        assert not item['model_features_verified']
        assert not item['model_calibration_verified']
        assert not item['live_executable_prices_verified']


def test_stale_partial_missing_and_unparseable_fail_closed():
    stale = verification_summary(sample(NOW-timedelta(hours=7)), now=NOW)
    assert stale['sports']['NBA']['status'] == 'STALE'
    missing = verification_summary(None, now=NOW)
    assert missing['sports']['NFL']['status'] == 'NOT_VERIFIED'
    partial = sample()
    partial['sports']['nba']['props'] = {'status': 'ACCESS_OK_EMPTY', 'rows': 0}
    result = verification_summary(partial, now=NOW)
    assert result['sports']['NBA']['status'] == 'NOT_VERIFIED'
    assert result['sports']['NFL']['status'] == 'SAMPLE_ACCESS_CONFIRMED'
    malformed = verification_summary({'observed_at': 'not-a-date', 'sports': {'nba': None}}, now=NOW)
    assert not malformed['fresh']
    assert malformed['sports']['NBA']['status'] == 'NOT_VERIFIED'


def test_verification_does_not_leak_raw_data_or_credentials():
    report = sample()
    report['api_key'] = 'supersecret'
    report['sports']['nba']['props']['raw_player'] = 'private-data'
    out = str(verification_summary(report, now=NOW))
    assert 'supersecret' not in out
    assert 'private-data' not in out


def test_member_endpoint_requires_authentication():
    client = TestClient(app)
    assert client.get('/v1/vip/player-feed-verification').status_code in (401, 403)

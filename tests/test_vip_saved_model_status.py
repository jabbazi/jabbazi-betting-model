"""Member readiness is persisted research, not a live vendor entitlement probe."""
from unittest.mock import Mock, patch
from datetime import UTC, datetime, timedelta

from test_member_portal import portal as _portal_fixture, sign_in
from jabazi.vip import data, model_status

portal = _portal_fixture


def test_models_and_boost_readiness_never_probe_live_providers(portal, monkeypatch):
    store, client = portal
    sign_in(store, client)
    forbid = Mock(side_effect=AssertionError('Member view attempted external provider request'))
    monkeypatch.setattr('jabazi.providers.player_features_live.LivePlayerFeatureCollector.provider_status', forbid)
    monkeypatch.setattr('jabazi.providers.balldontlie.BallDontLieProvider.fetch', forbid)
    monkeypatch.setattr('urllib.request.urlopen', forbid)
    monkeypatch.setattr('jabazi.api.platform_store', lambda: store)
    from jabazi.vip import model_cache
    monkeypatch.setattr(model_cache, 'status', lambda loader: {'state': 'READY', 'data': loader()})
    with patch.object(store, 'close'):
        assert client.get('/v1/vip/models').status_code == 200
        boost = client.get('/v1/vip/boost/status').json()
    assert boost['decision'] == 'PASS'
    assert boost['paid_requests_made'] == 0 and boost['betting_enabled'] is False
    forbid.assert_not_called()


def test_failed_model_load_is_generic_and_store_closes(portal, monkeypatch):
    store, _ = portal
    monkeypatch.setattr('jabazi.api.platform_store', lambda: store)
    monkeypatch.setattr(model_status, 'load_models', lambda store: ({}, ['private/file/path']))
    monkeypatch.setattr(model_status, 'load_player_models', lambda store: ({}, []))
    with patch.object(store, 'close') as close:
        result = model_status.saved_model_status()
    close.assert_called_once()
    assert result['errors'] == ['MODEL_EVIDENCE_UNAVAILABLE']
    assert 'private/file/path' not in str(result)
    assert all(row['status'] == 'UNAVAILABLE' for row in result['models'])


def test_official_display_preserves_real_health_provenance(portal):
    store, _ = portal
    now = datetime.now(UTC)
    payload = {'decision': 'BET_NOW', 'stake': '30', 'maximum_playable_decimal': '1.9',
        'model_probability': '.64', 'model_version': 'fixture-accepted-model',
        'reliability': {'model_can_influence_cash': True, 'model_stage': 'PRODUCTION_APPROVED',
                        'research_priority_components': {'data_health': 1}},
        'price': {'sport': 'basketball_nba', 'event_id': 'fixture-official', 'event': 'Away @ Home',
                  'market': 'h2h', 'selection': 'Home', 'best_book': 'Fixture', 'best_decimal': '2',
                  'executable': True, 'observed_at': now.isoformat(), 'source_timestamp': now.isoformat(),
                  'starts_at': (now + timedelta(hours=2)).isoformat()}}
    store.append('candidate', 'fixture', payload)
    row = data.official(store)[0]
    assert row['model_probability'] == .64 and row['approved_for_betting'] is True
    assert row['model_at'] != '' and row['data_health'] == 'HEALTHY'
    assert data.official(store, now=now+timedelta(minutes=6)) == []

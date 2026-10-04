from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jabazi.models.player_distribution import PlayerPropModel
from jabazi.providers.player_features_live import LivePlayerFeatureCollector
from jabazi.research.player_features import REQUIRED_INTEGRITY, archive_player_feature_snapshot
from test_player_prop_models import binary_artifact


def snapshot(*, research_only=False, provider='test-production', verified=None):
    now = datetime.now(UTC)
    class Store:
        def append(self, kind, entity, payload, key):
            self.payload = payload
        def list_records(self, *args, **kwargs):
            return [{'payload': self.payload}]
    store = Store()
    archive_player_feature_snapshot(
        store, sport='americanfootball_nfl', event_id='game', participant='Player',
        market='player_anytime_td', player_id='id', starts_at=(now+timedelta(hours=4)).isoformat(),
        features_available_at=now.isoformat(), features={'red_zone_share': .3},
        expected_opportunities=8, integrity=dict.fromkeys(REQUIRED_INTEGRITY, True),
        provider=provider, source_checksum='test', feature_schema_version='test',
        research_only=research_only, provider_data_verified=verified,
    )
    price = SimpleNamespace(sport='americanfootball_nfl', event_id='game', participant='Player',
        market='player_anytime_td', in_play=False, selection='yes', line=None,
        starts_at=datetime.fromisoformat(store.payload['starts_at']))
    artifact = binary_artifact() | {'stage':'PRODUCTION_APPROVED',
        'validation':{'promotion_passed':True,'prospective_sample_count':1000}}
    return store, price, PlayerPropModel(artifact, store)


def test_explicit_research_only_survives_all_green_integrity():
    store, price, model = snapshot(research_only=True)
    assert store.payload['research_only'] is True
    assert store.payload['production_inputs_verified'] is False
    assert model.estimate(price).approved_for_betting is False


def test_provider_authentication_is_not_data_authenticity(monkeypatch):
    monkeypatch.delenv('JABBAZI_SPORTSDATAIO_DATA_MODE', raising=False)
    collector = LivePlayerFeatureCollector(sportsdataio_api_key='test')
    with patch.object(collector, '_sportsdata') as request:
        assert collector._nfl_projections() == []
        assert collector._mlb_projections(datetime.now(UTC)) == []
        request.assert_not_called()
    assert len(collector.diagnostics) == 2


@pytest.mark.parametrize('verified', [None, False])
def test_legacy_or_unverified_sportsdata_snapshots_cannot_infer(verified):
    _, price, model = snapshot(provider='nflverse+SportsDataIO', verified=verified)
    assert model.estimate(price) is None


def test_verified_fresh_snapshot_can_infer():
    _, price, model = snapshot(provider='nflverse+SportsDataIO', verified=True)
    assert model.estimate(price) is not None


@pytest.mark.parametrize('fault', ['stale','future','started','wrong_start','naive'])
def test_snapshot_time_integrity(fault):
    store, price, model = snapshot()
    now = datetime.now(UTC)
    if fault == 'stale':
        store.payload['features_available_at'] = (now-timedelta(hours=2)).isoformat()
    elif fault == 'future':
        store.payload['features_available_at'] = (now+timedelta(minutes=1)).isoformat()
    elif fault == 'started':
        store.payload['starts_at'] = (now-timedelta(minutes=1)).isoformat()
    elif fault == 'wrong_start':
        price.starts_at += timedelta(hours=1)
    else:
        store.payload['features_available_at'] = now.replace(tzinfo=None).isoformat()
    assert model.estimate(price) is None


def test_mlb_history_ignores_future_recent_duplicate_and_unordered_rows():
    now = datetime(2026,9,28,12,tzinfo=UTC)
    collector = LivePlayerFeatureCollector(now=now, production_verified=True)
    card = SimpleNamespace(market='batter_hits',participant='Player',starts_at=now+timedelta(hours=6),
        sport='baseball_mlb',event_id='event')
    def row(day, value):
        return {'date':f'2026-09-{day:02}', 'game':{'gamePk':day},
                'stat':{'hits':value,'plateAppearances':4}}
    rows = [row(day, 1) for day in range(20,26)]
    rows += [row(27,99),row(28,99),row(29,99),row(20,99)]
    projection = {'PlayerID':1,'BattingOrder':1,'BattingOrderConfirmed':True,'PlateAppearances':4}
    with patch.object(collector,'_mlb_game_logs',return_value=list(reversed(rows[:-1]))+[rows[-1]]), \
         patch.object(collector,'_mlb_projection_for',return_value=projection), \
         patch.object(collector,'_mlb_person',return_value={'id':1}):
        result = collector.mlb_snapshot(card)
    assert result['features']['games_prior'] == 6
    assert result['features']['mean5_value'] == 1


def test_nfl_history_admission_uses_completed_game_availability():
    collector = LivePlayerFeatureCollector(now=datetime(2026,9,28,tzinfo=UTC))
    card = SimpleNamespace(market='player_anytime_td',participant='Player',
        starts_at=datetime(2026,9,29,tzinfo=UTC), sport='americanfootball_nfl',event_id='event')
    rows = [{'player_display_name':'Player','game_id':'future'}]
    with patch.object(collector,'_nfl_history',return_value=rows), \
         patch.object(collector,'_nfl_available_games',return_value={'future':datetime(2026,9,30,tzinfo=UTC)}):
        assert collector.nfl_snapshot(card) is None

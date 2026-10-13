from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from jabazi.daily_scope import eligible_today
from jabazi.discord_content import best_two_embed
from jabazi.discord_observations import observations
from jabazi.vip.data import board


@pytest.mark.parametrize('now,start,expected', [
    ('2026-10-14T03:00:00Z', '2026-10-14T04:59:00Z', True),
    ('2026-10-14T03:00:00Z', '2026-10-14T05:00:00Z', False),
    ('2026-10-14T05:00:00Z', '2026-10-14T04:59:00Z', False),
    ('2026-11-01T05:30:00Z', '2026-11-01T07:30:00Z', True),
    ('2026-03-08T07:30:00Z', '2026-03-08T09:30:00Z', True),
    ('2026-10-13T17:00:00Z', '2026-10-13T20:00:00', False),
])
def test_central_date_boundaries(now, start, expected):
    assert eligible_today({'starts_at': start}, now=datetime.fromisoformat(now)) is expected


@pytest.mark.parametrize('status', ['final', 'completed', 'postponed', 'cancelled', 'suspended'])
def test_inactive_games_never_reenter_feed_with_future_timestamp(status):
    now = datetime(2026, 10, 13, 17, tzinfo=UTC)
    assert not eligible_today({'starts_at': (now+timedelta(hours=2)).isoformat(), 'event_status': status}, now=now)


def test_board_and_observations_remove_future_events_without_altering_snapshot():
    now = datetime(2026, 10, 13, 17, tzinfo=UTC)
    today = {'sport': 'baseball_mlb', 'event_id': 'today', 'starts_at_utc': (now+timedelta(hours=2)).isoformat(),
             'market': 'h2h', 'model_version': 'fixture', 'research_probability': .7,
             'market_no_vig_probability': .5, 'price_time_utc': now.isoformat()}
    tomorrow = {**today, 'event_id': 'tomorrow', 'starts_at_utc': (now+timedelta(days=1)).isoformat()}
    record = {'id': 'snapshot', 'payload': {'healthy': True, 'completed_at': now.isoformat(), 'rows': [today, tomorrow, today]}}
    store = Mock()
    store.list_records.return_value = []
    assert [r['event_id'] for r in board(store, now=now, record=record)['rows']] == ['today']
    assert len(observations([record], lane='research', now=now)) == 1
    assert len(record['payload']['rows']) == 3
    assert len(board(store, now=now, record=record, historical=True)['rows']) == 2


def test_parlay_rechecks_all_legs_and_rejects_missing_dates():
    now = datetime(2026, 10, 13, 17, tzinfo=UTC)
    leg = {'starts_at': '2026-10-13T23:00:00Z', 'event': 'A @ B'}
    candidate = {'legs': [leg, dict(leg)]}
    assert best_two_embed(candidate, now=now)
    candidate['legs'][1]['starts_at'] = '2026-10-14T23:00:00Z'
    assert best_two_embed(candidate, now=now) is None
    candidate['legs'][1].pop('starts_at')
    assert best_two_embed(candidate, now=now) is None
    assert best_two_embed({'legs': [leg]}, now=now+timedelta(days=1)) is None


def test_daily_card_does_not_select_quarantined_model():
    from jabazi.discord_daily import _projection
    row = {'selection': 'Home', 'model_probability': .95, 'model_stage': 'QUARANTINED',
           'model_version': 'fixture', 'data_health': 'HEALTHY', 'status': 'QUARANTINED',
           'market_no_vig_probability': .55, 'executable': True}
    card = _projection({'event': 'Away @ Home'}, [row])
    assert card['projection_source'] == 'MARKET CONSENSUS'
    assert card['model_probability'] is None
    assert card['model_stage'] == 'UNAVAILABLE'


@pytest.mark.parametrize('change', ['rescheduled', 'missing', 'cancelled', 'old_scan', 'unhealthy', 'truncated'])
def test_queued_delivery_reconciles_latest_provider_observation(change):
    from jabazi.daily_scope import delivery_eligible
    now = datetime(2026, 10, 13, 17, tzinfo=UTC)
    queued = {'sport': 'baseball_mlb', 'event_id': 'g1', 'starts_at': '2026-10-13T23:00:00Z'}
    event = dict(queued)
    payload = {'healthy': True, 'completed_at': now.isoformat(), 'slate_events': [event]}
    store = Mock()
    store.list_records.return_value = [{'payload': payload}]
    assert delivery_eligible(store, [queued], now=now)
    if change == 'rescheduled':
        event['starts_at'] = '2026-10-14T23:00:00Z'
    elif change == 'missing':
        payload['slate_events'] = []
    elif change == 'cancelled':
        event['event_status'] = 'cancelled'
    elif change == 'old_scan':
        payload['completed_at'] = (now-timedelta(minutes=16)).isoformat()
    elif change == 'unhealthy':
        payload['healthy'] = False
    else:
        payload['truncated'] = True
    assert not delivery_eligible(store, [queued], now=now)
    assert queued['starts_at'] == '2026-10-13T23:00:00Z'


def test_delivery_does_not_merge_doubleheader_event_identities():
    from jabazi.daily_scope import delivery_eligible
    now = datetime(2026, 10, 13, 17, tzinfo=UTC)
    first = {'sport': 'baseball_mlb', 'event_id': 'g1', 'starts_at': '2026-10-13T23:00:00Z'}
    second = {**first, 'event_id': 'g2', 'starts_at': '2026-10-14T02:00:00Z'}
    store = Mock()
    store.list_records.return_value = [{'payload': {'healthy': True, 'completed_at': now.isoformat(), 'slate_events': [first, second]}}]
    assert delivery_eligible(store, [first, second], now=now)
    assert not delivery_eligible(store, [first, {**second, 'event_id': 'unknown'}], now=now)


def test_legacy_member_sheet_also_excludes_tomorrow_without_rewriting_history():
    from jabazi.member_api import daily_record
    now = datetime(2026, 10, 13, 17, tzinfo=UTC)
    today = {'starts_at_utc': '2026-10-13T23:00:00Z'}
    future = {'starts_at_utc': '2026-10-14T23:00:00Z'}
    record = {'payload': {'rows': [today, future]}}
    assert daily_record(record, now=now)['payload']['rows'] == [today]
    assert record['payload']['rows'] == [today, future]

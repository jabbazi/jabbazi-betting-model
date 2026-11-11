"""Synthetic records test polling mechanics, never calibration evidence."""
from datetime import UTC, datetime

import httpx
import pytest
from time_machine import travel

from jabazi.boost_prospective import FORECAST, RESULT
from jabazi.persistence.store import Store, digest
from tools import settle_joint_batch as batch
from tools.settle_joint_research import official_result
from tests.test_joint_official_results import fixture

NOW = datetime(2026, 11, 12, 4, tzinfo=UTC)


@pytest.fixture
def store():
    s = Store('sqlite://', initialize=True)
    yield s
    s.close()


def add(store, i, start='2026-11-12T00:00:00Z'):
    fid = f'{i:064x}'
    frozen, _ = fixture()
    frozen['starts_at'] = start
    store.append(FORECAST, 'synthetic', frozen, fid)
    return fid


def test_future_forecasts_do_not_fetch_or_write(store):
    add(store, 1, '2026-11-13T00:00:00Z')
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail('No fetch before start'))) as http:
        report = batch.settle_batch(store, http, execute=True, now=NOW)
    assert report['results'][0]['status'] == 'PENDING'
    assert not store.list_records(RESULT, 10)


def test_resolved_records_excluded_and_cursor_does_not_starve_later_records(store, monkeypatch):
    ids = [add(store, i) for i in range(1, 5)]
    store.append(RESULT, 'synthetic', {'forecast_id': ids[0]}, digest(['result', ids[0]]))
    monkeypatch.setattr(batch, 'settle_one', lambda *a, **k: {'status': 'PENDING'})
    first = batch.settle_batch(store, None, limit=1, now=NOW)
    assert first['results'][0]['forecast_id'] == ids[1]
    assert first['has_more'] and first['next_cursor'] == ids[1]
    rest = batch.settle_batch(store, None, after=first['next_cursor'], now=NOW)
    assert [r['forecast_id'] for r in rest['results']] == ids[2:]
    assert not rest['has_more'] and rest['next_cursor'] is None


def test_failed_player_does_not_stop_batch_and_errors_are_redacted(store, monkeypatch):
    ids = [add(store, i) for i in range(1, 3)]
    def settle(s, h, fid, **kwargs):
        assert kwargs['execute'] is False
        if fid == ids[0]:
            raise ValueError('PRIVATE SOURCE SECRET')
        return {'status': 'FINAL_VERIFIED_DRY_RUN'}
    monkeypatch.setattr(batch, 'settle_one', settle)
    report = batch.settle_batch(store, None, now=NOW)
    assert [r['status'] for r in report['results']] == ['BLOCKED', 'FINAL_VERIFIED_DRY_RUN']
    assert 'SECRET' not in str(report)


def test_shared_boxscore_still_checks_each_player():
    frozen, document = fixture()
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=document)
    cache = {}
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        official_result(http, frozen, 'a'*64, now=NOW, source_cache=cache)
        frozen['legs'][0]['player_id'] = '999'
        with pytest.raises(ValueError):
            official_result(http, frozen, 'b'*64, now=NOW, source_cache=cache)
    assert len(requests) == 1


@travel(NOW, tick=False)
def test_execute_archives_once_and_dry_run_never_archives(store):
    from tests.test_boost_joint_capture_cli import _frozen, NOW as CAPTURED
    from jabazi.boost_prospective import freeze_joint_ticket
    frozen = _frozen()
    frozen.update(sport='icehockey_nhl', event_id='nhl:123')
    frozen['model_source']['payload']['event_id'] = 'nhl:123'
    for leg, market in zip(frozen['legs'], ['player_goals', 'player_shots_on_goal']):
        leg.update(player_id='45', market=market)
    frozen['model_source']['payload']['legs'] = frozen['legs']
    freeze_joint_ticket(store, frozen, observed_at=CAPTURED)
    _, document = fixture()
    document['startTimeUTC'] = frozen['starts_at']
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=document))) as http:
        dry = batch.settle_batch(store, http, now=NOW)
        assert dry['results'][0]['status'] == 'FINAL_VERIFIED_DRY_RUN', dry
        assert not store.list_records(RESULT, 10)
        saved = batch.settle_batch(store, http, execute=True, now=NOW)
        assert saved['results'][0]['created'] is True
        assert len(store.list_records(RESULT, 10)) == 1
        assert batch.settle_batch(store, http, execute=True, now=NOW)['processed'] == 0


def test_deadline_returns_continuation_without_skipping(store, monkeypatch):
    add(store, 1)
    ticks = iter([0, 61])
    monkeypatch.setattr(batch.time, 'monotonic', lambda: next(ticks))
    report = batch.settle_batch(store, None, now=NOW)
    assert report['processed'] == 0 and report['has_more']
    assert report['next_cursor'] == ''


@pytest.mark.parametrize('kwargs', [{'limit': 201}, {'max_seconds': 0}, {'after': 'bad'}])
def test_invalid_bounds_rejected_before_query(kwargs):
    with pytest.raises(ValueError):
        batch.settle_batch(None, None, **kwargs)


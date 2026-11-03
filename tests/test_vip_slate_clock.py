from datetime import UTC, date, datetime
import pytest
from jabazi.vip.slate_clock import default_slate_date
from jabazi.daily_scope import eligible_today, reconciled_event
from jabazi.vip.data import board
from jabazi.vip.rankings import research_hub


@pytest.mark.parametrize('at,expected', [
    ('2026-10-14T03:59:59+00:00','2026-10-13'),
    ('2026-10-14T04:00:00+00:00','2026-10-14'),
    ('2026-10-14T04:58:00+00:00','2026-10-14'),
    ('2026-10-14T05:00:00+00:00','2026-10-14'),
    ('2026-11-02T04:59:59+00:00','2026-11-01'),
    ('2026-11-02T05:00:00+00:00','2026-11-02'),
    ('2026-03-09T04:00:00+00:00','2026-03-09'),
])
def test_central_11pm_rollover_including_dst(at, expected):
    assert default_slate_date(datetime.fromisoformat(at)).isoformat() == expected


def test_preview_never_changes_alert_date_or_price_age():
    now = datetime(2026,10,14,4,58,tzinfo=UTC)
    row = {'sport':'baseball_mlb','event_id':'next','event':'Away @ Home','market':'h2h',
           'selection':'Home','starts_at_utc':'2026-10-14T20:00:00+00:00',
           'price_time_utc':now.isoformat(),'decimal_odds':2,'market_no_vig_probability':.6,
           'executable':True}
    selected = default_slate_date(now)
    assert eligible_today(row, now=now, slate_date=selected)
    assert not eligible_today(row, now=now)
    assert reconciled_event(row, [row], now=now, slate_date=selected)
    assert not reconciled_event(row, [{**row,'starts_at_utc':'2026-10-15T20:00:00+00:00'}], now=now, slate_date=selected)
    class Store:
        def list_records(self, *a, **kw): return []
    record = {'id':'fixture','payload':{'healthy':True,'completed_at':now.isoformat(),'rows':[row],'slate_events':[row]}}
    assert not board(Store(), now=now, record=record)['rows']
    rows = board(Store(), now=now, record=record, slate_date=selected)['rows']
    assert len(rows) == 1 and rows[0]['fresh']
    assert len(research_hub(rows, now=now, slate_date=selected)['moneyline_likely']) == 1
    assert not research_hub(rows, now=now)['moneyline_likely']
    row['price_time_utc']='2026-10-14T04:00:00+00:00'
    rows = board(Store(), now=now, record=record, slate_date=selected)['rows']
    assert len(rows) == 1 and not rows[0]['fresh']
    assert not research_hub(rows, now=now, slate_date=selected)['moneyline_likely']


def test_explicit_current_date_remains_available():
    now=datetime(2026,10,14,4,10,tzinfo=UTC)
    row={'starts_at_utc':'2026-10-14T04:45:00+00:00'}
    assert eligible_today(row, now=now, slate_date=date(2026,10,13))
    assert not eligible_today(row, now=now, slate_date=default_slate_date(now))

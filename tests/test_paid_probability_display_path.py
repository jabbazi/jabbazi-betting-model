"""Synthetic pipeline acceptance; these fixtures are not live model evidence."""
from zoneinfo import ZoneInfo

import pytest

from jabazi.vip.data import board
from jabazi.vip.research import query_board
from tests.test_v7_paid_player_scan import NOW, PaidProvider, run


@pytest.mark.parametrize('sport', ['NBA', 'NFL', 'NHL'])
def test_paid_inference_reaches_full_player_board_without_lab(sport):
    report, store, provider = run(sports=(sport,), provider=PaidProvider(paginate=True))
    requests = len(store.charges)
    day = NOW.astimezone(ZoneInfo('America/Chicago')).date()
    saved = board(store, now=NOW, slate_date=day)
    view = query_board(saved, sport=sport, family='props')
    assert report['sports'][sport]['model_probability_rows'] > 0
    assert view['total'] == report['sports'][sport]['model_probability_rows']
    assert all(0 < row['model_probability'] < 1 for row in view['rows'])
    assert all(row['source'] == 'SAVED_PAID_MODEL_RESEARCH' for row in view['rows'])
    assert all(not row['approved_for_betting'] for row in view['rows'])
    assert len(store.charges) == requests


def test_missing_nhl_identity_does_not_become_a_probability():
    report, store, _ = run(sports=('NHL',), mappings=False)
    saved = board(store, now=NOW, slate_date=NOW.astimezone(ZoneInfo('America/Chicago')).date())
    view = query_board(saved, sport='NHL', family='props')
    assert report['sports']['NHL']['accepted_quotes'] > 0
    assert view['total'] == 0
    assert saved['paid_coverage']['NHL']['model_estimates_complete'] is False
    gaps = saved['paid_coverage']['NHL']['missing_probability_reasons']
    assert any(g['reason'] == 'MISSING_OR_AMBIGUOUS_CROSSWALK' for g in gaps)

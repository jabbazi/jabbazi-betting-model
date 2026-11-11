"""Synthetic book-isolation contracts; no live quote or calibration evidence."""
from types import SimpleNamespace

import pytest

from jabazi.boost_feed import collect_boost_odds
from jabazi.boost_scope import BoostScope, scope_from_text
from jabazi.paid_player_scan import PaidScanLimits, run_paid_player_scan, read_saved_boost_scan
from tests.test_v7_paid_player_scan import NOW, MemoryStore, PaidProvider, quote, seed


class Pages:
    def __init__(self, rows):
        self.rows = rows

    def fetch_all_pages(self, sport, resource, params, **kwargs):
        gid = dict(params)['game_id']
        return {'data': self.rows[gid], 'pages': 1, 'complete': True}


def scoped():
    return scope_from_text('NBA boost', bookmakers=['draftkings'])


def test_other_book_prices_cannot_fill_draftkings_coverage():
    rows = {77: [quote('NBA', vendor='fanduel')]}
    result = collect_boost_odds(Pages(rows), scoped(), game_ids=[77], observed_at=NOW)
    assert result.odds_rows == 0 and result.out_of_scope_rows == 1
    assert result.coverage == 'PARTIAL'
    assert result.game_row_counts == ((77, 0),)
    assert 'game:77:REQUESTED_BOOKMAKER_QUOTES_UNAVAILABLE' in result.errors


def test_only_requested_book_survives_and_partial_games_are_explicit():
    rows = {77: [quote('NBA', vendor=' DraftKings '), quote('NBA', id=101, vendor='fanduel')],
            78: [quote('NBA', game_id=78, vendor='fanduel')]}
    result = collect_boost_odds(Pages(rows), scoped(), game_ids=[77, 78], observed_at=NOW)
    assert result.odds_rows == 1 and result.out_of_scope_rows == 2
    assert result.game_row_counts == ((77, 1), (78, 0))
    assert result.coverage == 'PARTIAL'


def test_book_filter_preserves_market_and_freshness_gates():
    rows = {77: [quote('NBA', vendor='draftkings', prop_type='rebounds'),
                 quote('NBA', id=102, vendor='draftkings', updated_at='2020-01-01T00:00:00Z')]}
    scope = BoostScope('basketball_nba', markets=frozenset({'points'}), bookmakers=frozenset({'draftkings'}))
    result = collect_boost_odds(Pages(rows), scope, game_ids=[77], observed_at=NOW)
    assert result.odds_rows == 0 and result.stale_rows == 1 and result.out_of_scope_rows == 1


def test_unscoped_scanner_keeps_existing_multi_book_behavior():
    result = collect_boost_odds(Pages({77: [quote('NBA', vendor='fanduel')]}),
        BoostScope('basketball_nba'), game_ids=[77], observed_at=NOW)
    assert result.coverage == 'FULL' and result.odds_rows == 1


def test_unknown_book_identity_remains_invalid_not_merely_out_of_scope():
    rows = {77: [quote('NBA', vendor='draftkings'), quote('NBA', id=101, vendor=None)]}
    result = collect_boost_odds(Pages(rows), scoped(), game_ids=[77], observed_at=NOW)
    assert result.odds_rows == 1 and result.invalid_rows == 1
    assert result.out_of_scope_rows == 0 and result.coverage == 'PARTIAL'


@pytest.mark.parametrize('books', [frozenset({''}), frozenset({'DraftKings'}), frozenset({'bad book'}), ['draftkings']])
def test_malformed_scope_is_not_silently_broadened(books):
    with pytest.raises(ValueError):
        BoostScope('basketball_nba', bookmakers=books)


def test_paid_scan_does_not_archive_other_book_as_requested_book_evidence():
    store = MemoryStore()
    models = seed(store, ('NBA',))
    provider = PaidProvider()
    result = run_paid_player_scan(store,
        SimpleNamespace(balldontlie_api_key='fixture', balldontlie_lab_api_key=''),
        models, lambda: True, now=NOW, sports=('NBA',), boost_scope=scoped(),
        limits=PaidScanLimits(requests=10, seconds=60, interval=0),
        provider_factory=lambda *a, **k: provider,
        lab_reader=lambda *a, **k: {'state': 'UNAVAILABLE', 'rows': [], 'coverage_complete': False})
    sport = result['sports']['NBA']
    assert sport['requested_bookmakers'] == ['draftkings']
    assert sport['accepted_quotes'] == 0 and sport['model_probability_rows'] == 0
    assert not result['scope_complete']
    assert not store.list_records('paid_player_quote_snapshot', 10)
    assert not store.list_records('paid_player_scan', 10)
    assert len(store.list_records('paid_boost_scan', 10)) == 1
    assert read_saved_boost_scan(store, scoped(), now=NOW)['sports']['NBA']['requested_bookmakers'] == ['draftkings']
    other = BoostScope('basketball_nba', bookmakers=frozenset({'fanduel'}))
    assert read_saved_boost_scan(store, other, now=NOW)['status'] == 'UNAVAILABLE'

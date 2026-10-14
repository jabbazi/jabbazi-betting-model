from datetime import UTC, datetime, timedelta

import pytest

from jabazi.vip.rankings import research_hub
from jabazi.vip.game_research import score_histograms
from jabazi.models.game_distribution import GameDistribution

NOW = datetime(2026, 10, 15, 18, tzinfo=UTC)


def row(**changes):
    return {'id': 'one', 'sport': 'NFL', 'event_id': 'thursday', 'event': 'Away @ Home',
            'starts_at': (NOW+timedelta(hours=6)).isoformat(), 'price_at': NOW.isoformat(),
            'lifecycle': 'UPCOMING', 'status': 'WATCH', 'fresh': True,
            'market': 'h2h', 'selection': 'Home', 'player': None, 'decimal': 1.8,
            'line': None, 'market_probability': .6, 'model_probability': None,
            'model_stage': 'UNAVAILABLE', 'data_health': 'HEALTHY', **changes}


def test_thursday_only_and_market_fallback_without_fake_model():
    data = research_hub([row(), row(event_id='sunday', starts_at=(NOW+timedelta(days=3)).isoformat())], sport='NFL', now=NOW)
    assert data['game_count'] == 1
    assert len(data['moneyline_likely']) == 1
    assert data['moneyline_likely'][0]['evidence_label'] == 'MARKET-CONSENSUS LEAN'
    assert data['moneyline_likely'][0]['model_probability'] is None
    assert not data['moneyline_value']


@pytest.mark.parametrize('change', [{'fresh': False}, {'price_at': (NOW-timedelta(minutes=6)).isoformat()},
                                   {'status': 'QUARANTINED'}, {'lifecycle': 'EXPIRED'},
                                   {'starts_at': (NOW-timedelta(hours=1)).isoformat()}])
def test_ineligible_or_stale_not_ranked(change):
    assert not research_hub([row(**change)], now=NOW)['moneyline_likely']


def test_receiving_over_exact_line_and_no_fabricated_yardage_mean():
    data = research_hub([row(market='player_reception_yds', player='Receiver', selection='Over', line=64.5)], now=NOW)
    assert data['receiving_overs'][0]['line'] == 64.5
    assert not data['receiving_totals']
    assert len(data['receiving_overs']) == 1


def test_value_requires_approved_model_and_positive_ev():
    base = row(model_probability=.7, model_version='test', model_stage='SHADOW_ONLY')
    assert not research_hub([base], now=NOW)['moneyline_value']
    assert len(research_hub([{**base, 'model_stage':'PRODUCTION_APPROVED'}], now=NOW)['moneyline_value']) == 1


def test_td_excludes_passing_first_td_and_no_outcome():
    rows = [row(market=m, player='Player', selection=s) for m,s in
            [('player_anytime_td','Yes'),('player_anytime_td','No'),('player_pass_tds','Over'),('player_first_td','Yes')]]
    assert len(research_hub(rows, now=NOW)['anytime_td']) == 1


def source(selection='Home', **changes):
    return {'payload': {'sport':'americanfootball_nfl','event_id':'thursday','market':'h2h',
                        'selection':selection,'independently_agreed':True,
                        'source_url':'https://www.nfl.com/news/example','source':'NFL',
                        'observed_at':NOW.isoformat(),'posted_at':NOW.isoformat(), **changes}}


def test_reviewed_evidence_and_conflicts():
    result = research_hub([row()], now=NOW, source_picks=[source()])
    assert result['web_leans'][0]['model_probability'] is None
    assert not research_hub([row()], now=NOW, source_picks=[source(),source('Away')])['web_leans']
    assert not research_hub([row()], now=NOW, source_picks=[source(independently_agreed=False)])['web_leans']
    assert not research_hub([row()], now=NOW, source_picks=[source(source_url='javascript:alert(1)')])['web_leans']


def test_empty_day_and_late_chicago_game():
    assert research_hub([], now=NOW)['game_count'] == 0
    late = datetime(2026, 10, 16, 3, tzinfo=UTC)
    assert research_hub([row(starts_at=late.isoformat())], now=NOW)['game_count'] == 1
    assert research_hub([row(starts_at=late.isoformat())], now=late+timedelta(hours=3))['game_count'] == 0


def test_score_histograms_preserve_probability_mass():
    d = GameDistribution(tuple([(24,17)]*70+[(17,24)]*30))
    hist = score_histograms(d)
    for bins in hist.values():
        assert sum(b['probability'] for b in bins) == pytest.approx(1)
    assert hist['total'] == [{'low':41,'high':41,'probability':pytest.approx(1)}]

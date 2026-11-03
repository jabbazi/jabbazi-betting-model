"""Projected stat totals must be fitted means, never sportsbook thresholds."""
from datetime import UTC, datetime, timedelta

from jabazi.vip.data import project

NOW = datetime(2026, 10, 26, 16, tzinfo=UTC)


def raw(**kw):
    r = {
        'sport':'basketball_nba', 'event_id':'g1', 'event':'Away @ Home',
        'starts_at_utc':(NOW+timedelta(hours=4)).isoformat(),
        'price_time_utc':NOW.isoformat(), 'market':'player_points',
        'participant':'Player', 'selection':'Over', 'line':24.5,
        'decimal_odds':1.9, 'market_no_vig_probability':.52,
        'research_probability':.56, 'model_version':'v5',
        'model_stage':'VALIDATING', 'data_health':'HEALTHY',
        'executable':True,
    }
    return {**r,**kw}


def record(r):
    return {'id':'snap','payload':{
        'healthy':True,'completed_at':NOW.isoformat(),
        'rows':[r]}}


def test_projected_mean_requires_explicit_versioned_distribution():
    r=raw(player_distribution={'market':'player_points','model_version':'v5','mean':27.3})
    item=project(r,record(r),NOW)
    assert item['projected_mean']==27.3
    assert item['projection_basis']=='FITTED DISTRIBUTION'


def test_no_mean_from_sportsbook_line_or_mismatched_artifact():
    r=raw()
    assert project(r,record(r),NOW)['projected_mean'] is None
    for d in ({'market':'player_points','model_version':'old','mean':29},
              {'market':'player_assists','model_version':'v5','mean':8}):
        r=raw(player_distribution=d)
        assert project(r,record(r),NOW)['projected_mean'] is None

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from jabazi.research.nfl_atd_experiment import available, build_rows, features, split_rows


def fixture_games():
    source, schedule = [], {}
    start = datetime(2023, 10, 1, 17, tzinfo=UTC)
    for i in range(8):
        s=(start+timedelta(days=7*i)).isoformat();gid=f'g{i}'
        schedule[gid]={'home_team':'A','away_team':'B','starts_at':s,'season':'2023','week':str(i+1),'home_score':'21','away_score':'14'}
        for player,t,o in [('p1','A','B'),('p2','A','B'),('p3','B','A')]:
            source.append({'event_id':gid,'player_id':player,'team':t,'opponent':o,'is_home':t=='A',
                'starts_at':s,'season':2023,'week':i+1,'position':'RB', 'carries':10.,'targets':3.,
                'rushing_tds':float(player=='p1'),'receiving_tds':0.,'touch_opportunities':13.,'anytime_td':float(player=='p1')})
    return source,schedule


def test_current_game_outcomes_do_not_change_its_features_or_other_players_features():
    source,schedule=fixture_games();original=build_rows(source,schedule)
    altered=deepcopy(source)
    for r in altered:
        if r['event_id']=='g5':r.update(carries=1000.,targets=900.,rushing_tds=30.,anytime_td=1.)
    revised=build_rows(altered,schedule)
    for a,b in zip(original,revised):
        if a['event_id']<='g5':
            assert a['features']==b['features']
            assert a['baseline_features']==b['baseline_features']
    assert any(a['features']!=b['features'] for a,b in zip(original,revised) if a['event_id']>'g5')


def test_sorted_vs_shuffled_input_gives_identical_feature_snapshots():
    source,schedule=fixture_games()
    a=sorted(build_rows(source,schedule),key=lambda r:(r['event_id'],r['player_id']))
    b=sorted(build_rows(list(reversed(source)),schedule),key=lambda r:(r['event_id'],r['player_id']))
    assert a==b


def test_source_duplicates_wrong_opponents_and_week_are_rejected():
    source,schedule=fixture_games()
    with pytest.raises(ValueError,match='Duplicate'):build_rows(source+[source[0]],schedule)
    for field,value in [('opponent','C'),('week',19),('is_home',False)]:
        bad=deepcopy(source);bad[0][field]=value
        with pytest.raises(ValueError):build_rows(bad,schedule)


def test_features_are_read_from_prior_opportunities_not_current_outcomes():
    source,_=fixture_games();row=source[-1]
    prior=[r|{'carry_share':.5,'target_share':.5} for r in source[:3]]
    a=features(prior,[],[],row)
    changed=row|{'carries':100,'rushing_tds':30,'anytime_td':1}
    assert features(prior,[],[],changed)==a
    assert 'rushing_tds_mean3' in a and 'receiving_tds_mean3' in a
    assert not any('red_zone' in name for name in a)


def test_availability_embargo_and_grouped_partition():
    source,schedule=fixture_games(); rows=build_rows(source,schedule)
    decision=datetime(2023,10,3,17,tzinfo=UTC)
    assert available(source[:3],decision)==[]
    assert len(available(source[:3],decision+timedelta(seconds=1)))==3
    p=split_rows(rows)
    assert {r['event_id'] for r in p['train']}.isdisjoint(r['event_id'] for r in p['calibration'])
    bad=deepcopy(rows);bad[0]['feature_history_cutoff']=bad[0]['starts_at']
    with pytest.raises(ValueError,match='look-ahead'):split_rows(bad)

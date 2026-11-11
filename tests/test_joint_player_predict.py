"""Synthetic mechanics tests, never prospective model-validation evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import pytest

from jabazi.research.joint_player_fit import SPECS, fingerprint
from jabazi.research.joint_player_predict import FrozenJointResearchModel
from jabazi.research.player_features import REQUIRED_INTEGRITY
from jabazi.persistence.store import Store
from jabazi.boost_prospective import audit_ready_rows
from tools.capture_joint_research import load_frozen_model, official_scope
import httpx

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


def fixture():
    sport = 'icehockey_nhl'
    marginals = {market: {'sport': sport, 'market': market, 'family': 'count_nb',
        'training_cutoff': '2018-01-01T00:00:00Z', 'model_version': 'synthetic-'+market,
        'calibration': None, 'feature_names': ['x'], 'scaler': {'mean': [0.], 'scale': [1.]},
        'parameters': {'coef': [0.], 'intercept': 1., 'dispersion': .2}}
        for pair, _ in SPECS[sport] for market in pair}
    buckets = [{'markets': list(pair), 'benchmark_lines': list(lines),
                'status': 'HISTORICAL_RESEARCH_FIT', 'ranks': [[i,i] for i in range(200)],
                'training_unique_games': 200, 'test_unique_games': 200, 'training_pairs': 200}
               for pair, lines in SPECS[sport]]
    a = {'artifact_type': 'same_player_joint_research', 'stage': 'SHADOW_ONLY',
         'approved_for_betting': False, 'sport': sport,
         'fit_start': '2019-01-01T00:00:00+00:00', 'test_start': '2020-01-01T00:00:00+00:00',
         'test_end': '2021-01-01T00:00:00+00:00', 'buckets': buckets,
         'sources': {m: {'marginal_sha256': fingerprint(v)} for m,v in marginals.items()}}
    identity = {'sport': sport, 'fit_start': a['fit_start'], 'fit_end': a['test_start'],
                'marginals': {m: fingerprint(v) for m,v in marginals.items()},
                'buckets': [{k:b[k] for k in ('markets','ranks','benchmark_lines')} for b in buckets]}
    a['model_version'] = sport+'-joint-research-'+fingerprint(identity)[:12]
    return a,marginals


def model():
    a,m=fixture()
    return FrozenJointResearchModel(a,m,expected_sha256=fingerprint(a),fitted_at='2021-01-02T00:00:00Z')


def snapshots():
    result=[]
    for market in ('player_goals','player_shots_on_goal'):
        s={'sport':'icehockey_nhl','event_id':'nhl:fixture','player_id':'fixture-player',
           'market':market,'participant':'Synthetic Fixture','features':{'x':1.},
           'starts_at':(NOW+timedelta(hours=2)).isoformat(),
           'features_available_at':NOW.isoformat(),'source_checksum':'synthetic-only',
           'roster_version':'BOS','provider':'synthetic-only','research_only':False,
           'production_inputs_verified':True,
           'integrity':{k:True for k in REQUIRED_INTEGRITY}}
        s['snapshot_id']='playerfs-'+fingerprint(s)[:20]
        s['archived_at']=NOW.isoformat()
        result.append(s)
    return result


def test_computes_and_freezes_fitted_benchmark_without_fabricating_book_quote():
    m=model(); ss=snapshots()
    t=m.ticket(ss,now=NOW)
    assert 0<t['joint_probability']<1
    assert t['model_source']['payload']['benchmark_only'] is True
    assert 'market_source' not in t and 'offered_quote' not in t
    assert [x['line'] for x in t['legs']]==[.5,2.5]
    store=Store('sqlite:///:memory:',initialize=True)
    try:
        result=m.freeze(store,ss,now=NOW)
        assert result['created'] is True
        assert store.list_records('boost_joint_forecast',1)[0]['payload']['approved_for_betting'] is False
        assert audit_ready_rows(store)==[]
    finally: store.close()


@pytest.mark.parametrize('mutation',['tampered','other_player','other_event','unavailable','stale','in_play','future_archive','missing_feature'])
def test_unverified_inputs_never_produce_joint_forecasts(mutation):
    ss=snapshots(); s=ss[1]
    if mutation=='tampered': s['features']['x']=2.
    elif mutation=='other_player': s['player_id']='other'
    elif mutation=='other_event': s['event_id']='other'
    elif mutation=='unavailable': s['integrity']['availability']=False
    elif mutation=='stale': s['features_available_at']=(NOW-timedelta(minutes=11)).isoformat()
    elif mutation=='in_play': s['starts_at']=NOW.isoformat()
    elif mutation=='future_archive': s['archived_at']=(NOW+timedelta(seconds=1)).isoformat()
    else: s['features']={}
    if mutation!='tampered':
        s['snapshot_id']='playerfs-'+fingerprint({k:v for k,v in s.items() if k not in ('snapshot_id','archived_at')})[:20]
    with pytest.raises(ValueError): model().ticket(ss,now=NOW)


def test_artifact_and_marginal_custody_are_both_enforced():
    a,m=fixture(); checksum=fingerprint(a)
    tampered=deepcopy(m); tampered['player_goals']['parameters']['intercept']=2.
    with pytest.raises(ValueError):
        FrozenJointResearchModel(a,tampered,expected_sha256=checksum,fitted_at='2021-01-02T00:00:00Z')
    a['buckets'][0]['ranks'][0]=[1,1]
    with pytest.raises(ValueError):
        FrozenJointResearchModel(a,m,expected_sha256=checksum,fitted_at='2021-01-02T00:00:00Z')


@pytest.mark.parametrize('sport',['basketball_nba','icehockey_nhl'])
def test_checked_in_research_transport_matches_exact_frozen_marginals(sport):
    assert len(load_frozen_model(sport).buckets)==3


def test_official_nhl_scope_checks_game_state_and_exact_roster_id():
    def handle(request):
        if request.url.path.endswith('/landing'):
            return httpx.Response(200,json={'id':123,'gameState':'FUT',
                'startTimeUTC':(NOW+timedelta(hours=2)).isoformat(),
                'awayTeam':{'abbrev':'BOS'},'homeTeam':{'abbrev':'NYR'}})
        roster={'forwards':[{'id':45,'firstName':{'default':'Fixture'},'lastName':{'default':'Player'}}]} if '/BOS/' in request.url.path else {}
        return httpx.Response(200,json=roster)
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        scope=official_scope(http,'NHL','123','45',NOW)
        assert scope['event_id']=='nhl:123' and scope['player_id']=='45'
        with pytest.raises(ValueError): official_scope(http,'NHL','123','46',NOW)

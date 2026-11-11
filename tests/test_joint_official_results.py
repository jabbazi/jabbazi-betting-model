"""Synthetic boxscore contracts only; these fixtures are not calibration evidence."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import io

import httpx
import pytest

from jabazi.providers import nba_player_features as nba
from tools.settle_joint_research import official_result

NOW = datetime(2026, 11, 12, 4, tzinfo=UTC)


def fixture():
    f = {'sport':'icehockey_nhl','event_id':'nhl:123','ticket_id':'fixture',
         'starts_at':'2026-11-12T00:00:00Z','legs':[
             {'leg_id':'a','player_id':'45','market':'player_goals'},
             {'leg_id':'b','player_id':'45','market':'player_shots_on_goal'}]}
    d = {'id':123,'gameState':'OFF','startTimeUTC':f['starts_at'],
         'playerByGameStats':{'awayTeam':{'forwards':[{'playerId':45,'toi':'12:30','goals':1,'sog':3}],
             'defense':[]},'homeTeam':{'forwards':[],'defense':[]}}}
    return f,d


def result(f,d):
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200,json=d))) as http:
        return official_result(http,f,'f'*64,now=NOW)


def test_actual_stats_are_matched_by_id_and_completion_is_observed_not_invented():
    f,d=fixture()
    r=result(f,d)
    assert [v['observed_value'] for v in r['leg_results']]==[1,3]
    p=r['result_source']['payload']
    assert p['final_observed_at']==NOW.isoformat() and 'completed_at' not in p
    assert p['raw_response']==d and len(p['raw_response_sha256'])==64


@pytest.mark.parametrize('state',['FUT','PRE','LIVE','CRIT'])
def test_unfinished_games_cannot_be_settled(state):
    f,d=fixture(); d['gameState']=state
    assert result(f,d)['status']=='PENDING'


@pytest.mark.parametrize('mutation',['missing_player','missing_stat','wrong_game','changed_start','no_participation'])
def test_missing_or_mismatched_evidence_is_never_zero_filled(mutation):
    f,d=fixture()
    p=d['playerByGameStats']['awayTeam']['forwards'][0]
    if mutation=='missing_player': p['playerId']=46
    if mutation=='missing_stat': del p['sog']
    if mutation=='wrong_game': d['id']=124
    if mutation=='changed_start': d['startTimeUTC']='2026-11-12T01:00:00Z'
    if mutation=='no_participation': p['toi']='00:00'
    with pytest.raises((ValueError,KeyError)): result(f,d)


def test_nba_exact_labels_and_dnp():
    f,_=fixture(); f.update(sport='basketball_nba',event_id='espn-nba:123')
    f['legs'][0]['market']='player_points'; f['legs'][1]['market']='player_rebounds'
    d={'header':{'id':'123','competitions':[{'date':f['starts_at'],
        'status':{'type':{'state':'post','completed':True}}}]},
       'boxscore':{'players':[{'statistics':[{'labels':['MIN','PTS','REB'],
           'athletes':[{'athlete':{'id':'45'},'stats':['30','21','7']}]}]}]}}
    assert [x['observed_value'] for x in result(f,d)['leg_results']]==[21,7]
    d2=deepcopy(d); d2['boxscore']['players'][0]['statistics'][0]['athletes'][0]={'athlete':{'id':'45'},'didNotPlay':True}
    assert all(x['status']=='dnp' for x in result(f,d2)['leg_results'])


def test_large_csv_spools_in_bounded_chunks_and_preserves_checksum(monkeypatch):
    raw=b'column\n'+b'value\n'*30000
    class Response(io.BytesIO):
        def read(self,size=-1):
            assert 0<size<=65536
            return super().read(size)
    monkeypatch.setattr(nba.urllib.request,'urlopen',lambda *a,**k:Response(raw))
    stream,checksum=nba._csv_download('https://example.test/synthetic')
    with stream:
        assert sum(1 for _ in stream)==30001
    assert checksum==hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError): nba._csv_download('https://example.test/synthetic',max_bytes=10)

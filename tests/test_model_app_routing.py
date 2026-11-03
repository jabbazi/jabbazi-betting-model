"""Real fitted model -> action -> archive -> authenticated VIP -> Discord routing.

All quotes, feature inputs, users and memberships are synthetic test fixtures.
Passing these tests is NOT proof of live paid-feed coverage or calibration.
"""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from time_machine import travel
from test_member_portal import portal as _portal_fixture, sign_in
from test_score_models import artifact as team_artifact, card as team_card
from test_vip_research_repair import ordinary
from jabazi.automation import select_model
from jabazi.discord_research_views import summary, safe
from jabazi.discord_sheets import archive_sheets
from jabazi.domain.recommendation import recommend_price
from jabazi.domain.risk import RiskPolicy
from jabazi.domain.shopping import PriceCard
from jabazi.models.nhl_goals import NHLGoalsModel
from jabazi.models.player_distribution import PlayerPropModel, distribution_mean, BINARY_MARKETS, PLAYER_PROP_MARKETS
from jabazi.reliability.layer import evaluate
from jabazi.vip import data
from jabazi.vip.research import SPORT_CODES, moneyline_board
from jabazi.vip.model_routing import routing_report

portal = _portal_fixture


@pytest.fixture(autouse=True)
def isolated_member_rate_state(monkeypatch):
    # Every case owns a different disposable database/member session. Do not
    # conflate 74 independent clients into the shared TestClient host quota.
    monkeypatch.setattr('jabazi.vip.security._buckets', {})
ARTIFACTS = sorted(Path('models/player_props').glob('*/*.json'))


def archived_action(store, price, estimate, model, *, now):
    reliability = evaluate(price, estimate, model)
    action = recommend_price(price, RiskPolicy(D(3000)), model_probability=estimate.probability if estimate else None,
                             uncertainty=estimate.uncertainty if estimate else D(0), model_validated=False)
    action = replace(action, model_version=estimate.model_version if estimate else None, reliability=reliability)
    archive_sheets(store, SimpleNamespace(actions=[action], errors=[], feeds_scanned=1, quotes_archived=2,
        slate_events=[{'sport':price.sport,'event_id':price.event_id,'event':price.event,
                       'starts_at_utc':price.starts_at.isoformat(),'event_status':'scheduled'}]), now=now)
    return reliability


def player_fixture(store, artifact, *, alternate=False, side='over'):
    now = datetime.now(UTC)
    start = now+timedelta(hours=2)
    features = dict(zip(artifact['feature_names'], artifact['scaler']['mean'], strict=True))
    mean, _ = distribution_mean(artifact, features)
    market = artifact['market']
    line = D('.5') if market in BINARY_MARKETS else D(str(max(0, int(mean)) + .5))
    name, event = 'Synthetic routing player', 'synthetic-game'
    snapshot = {'sport': artifact['sport'], 'event_id': event, 'participant': name,
                'market': market, 'features_available_at': (now-timedelta(seconds=20)).isoformat(),
                'starts_at': start.isoformat(), 'provider': 'SYNTHETIC_ROUTING_FIXTURE',
                'features': features, 'research_only': True, 'production_inputs_verified': False,
                'integrity': {k: True for k in ('event_identity','player_identity','fresh_features','schema',
                                               'role','availability','injuries','no_duplicate_event')}}
    store.append('player_feature_snapshot', f"{artifact['sport']}|{event}|{name}|{market}", snapshot)
    price = PriceCard(artifact['sport'], event, 'Synthetic Away @ Synthetic Home',
                      market+('_alternate' if alternate else ''), name, side, line,
                      {'Synthetic book': D(2)}, 'Synthetic book', D(2), D('.5'), D(0), D(0),
                      False, False, ('fixture-quote',), now, now, start,
                      book_no_vig={'Synthetic book': D('.5')}, executable=True)
    model = PlayerPropModel(artifact, store)
    selected, inference = select_model(price, {}, {(artifact['sport'], market): model})
    assert selected is model and inference.market == market
    estimate = model.estimate(inference)
    if estimate is None:
        assert side == 'under' and artifact.get('calibration') and artifact['calibration'].get('orientation') != 'positive'
        return price, model, None, mean, now
    # Keep the synthetic comparison close; exercise routing, not admission of an edge.
    price = replace(price, consensus_probability=estimate.probability,
                    book_no_vig={'Synthetic book': estimate.probability})
    return price, model, estimate, mean, now


@pytest.mark.parametrize('path', ARTIFACTS, ids=lambda p: p.parent.name+'/'+p.stem)
@pytest.mark.parametrize('alternate,side', [(False,'over'), (True,'under')])
def test_every_bundled_player_market_reaches_authenticated_app_and_discord(portal, path, alternate, side):
    store, client = portal
    artifact = json.loads(path.read_text())
    price, model, estimate, mean, now = player_fixture(store, artifact, alternate=alternate, side=side)
    rel = archived_action(store, price, estimate, model, now=now)
    assert rel['model_can_influence_cash'] is False
    if estimate is None:
        assert rel['model_routing_reason'] == 'UNVERIFIED_NEGATIVE_SIDE_CALIBRATION'
        label = next(k for k,v in SPORT_CODES.items() if v == price.sport)
        sign_in(store, client)
        row = client.get('/v1/vip/board', params={'sport':label,'family':'props'}).json()['rows'][0]
        assert row['model_probability'] is None and row['projected_mean'] is None
        assert row['probability_unavailable_reason'] == 'UNVERIFIED_NEGATIVE_SIDE_CALIBRATION'
        assert 'under/no-side calibration' in summary(store, view='props',sport=label)['embed']['fields'][0]['value']
        return
    assert rel['player_distribution']['market'] == price.market
    assert rel['player_distribution']['model_version'] == estimate.model_version
    label = next(k for k,v in SPORT_CODES.items() if v == price.sport)
    sign_in(store, client)
    report = client.get('/v1/vip/board', params={'sport':label,'family':'props','market':price.market}).json()
    assert report['total'] == 1
    row = report['rows'][0]
    assert row['model_probability'] == pytest.approx(float(estimate.probability))
    assert row['projected_mean'] == (None if artifact['market'] in BINARY_MARKETS else pytest.approx(mean))
    assert row['model_stage'] == artifact['stage'] and row['approved_for_betting'] is False
    assert client.get('/v1/vip/detail/'+row['id']).json()['row']['model_version'] == estimate.model_version
    probabilities = client.get('/v1/vip/player-probabilities', params={'sport':label})
    assert probabilities.status_code == 200
    assert probabilities.json()['model_estimate_rows'] == 1
    assert probabilities.json()['top10'][0]['market'] == price.market
    discord = summary(store, view='props', sport=label, market=price.market, now=now)
    assert discord['row_ids'] == [row['id']] and discord['paid_requests_made'] == 0
    assert safe(estimate.model_version, 80) in discord['embed']['fields'][0]['value']
    assert discord['approved_for_betting'] is False


def test_matrix_covers_all_current_artifacts_and_declares_unfitted_markets():
    assert len(ARTIFACTS) == 37
    actual = {(json.loads(p.read_text())['sport'], json.loads(p.read_text())['market']) for p in ARTIFACTS}
    registered = {(s,m) for s, markets in PLAYER_PROP_MARKETS.items() for m in markets}
    assert registered-actual == {('icehockey_nhl','player_power_play_points'),('icehockey_nhl','player_blocked_shots')}


@pytest.mark.parametrize('league', ['NFL','CFB','NBA','NHL','MLB'])
def test_all_team_leagues_reach_moneyline_app_and_same_discord_snapshot(portal, league):
    store, client = portal
    ordinary(store, sport=SPORT_CODES[league], model_version='synthetic-'+league,
             event_id=league+'-game', model_stage='SHADOW_ONLY')
    sign_in(store, client)
    response = client.get('/v1/vip/moneylines', params={'sport':league}).json()
    assert response['total'] == 1
    game = response['games'][0]
    assert game['predicted_winner'] == 'Home' and game['model_probability'] == .64
    message = summary(store, view='moneylines', sport=league)
    assert message['row_ids'] == [game['model']['id']]
    assert response['snapshot_id'] in message['snapshot_ids']
    assert '64.0%' in message['embed']['fields'][0]['value']


def test_nhl_unique_cross_provider_identity_survives_archive_and_moneyline_display(portal):
    store, _ = portal
    artifact = team_artifact('nhl')
    price = team_card(artifact)
    model = NHLGoalsModel(artifact)
    estimate = model.estimate(price)
    assert estimate is not None
    assert estimate.feature_snapshot['integrity']['event_identity'] is True
    assert estimate.feature_snapshot['integrity']['event_identity_method'] == 'UNIQUE_CANONICAL_TEAMS_AND_START'
    assert estimate.feature_snapshot['odds_event_id'] == price.event_id
    price = replace(price, consensus_probability=estimate.probability,
                    book_no_vig={'Synthetic book':estimate.probability}, executable=True)
    with travel(price.observed_at):
        rel = archived_action(store,price,estimate,model,now=price.observed_at)
        assert 'UNVERIFIED_EVENT_IDENTITY' not in rel['anomaly_reasons']
        saved = data.board(store,now=price.observed_at,slate_date=price.starts_at.astimezone(ZoneInfo('America/Chicago')).date())
        game = moneyline_board(saved,sport='NHL')['games'][0]
        assert game['model_probability'] == pytest.approx(float(estimate.probability))
        assert not game['approved_for_betting'] and not rel['model_can_influence_cash']


@pytest.mark.parametrize('change',['id_conflict','empty_odds_id','shifted_start','reversed_teams','ambiguous','unscheduled','completed','wrong_season'])
def test_nhl_identity_fix_does_not_accept_conflicting_or_ambiguous_games(change):
    artifact = team_artifact('nhl'); price = team_card(artifact)
    event = next(e for e in artifact['events'] if e['home_team'] == price.selection and
                 e['away_team'] == price.event.split(' @ ')[0])
    if change=='id_conflict': event['provider_event_id']='conflicting-sportsbook-id'
    if change=='empty_odds_id': price=replace(price,event_id='')
    if change=='shifted_start': price=replace(price,starts_at=price.starts_at+timedelta(minutes=5))
    if change=='reversed_teams': price=replace(price,event=' @ '.join(reversed(price.event.split(' @ '))))
    if change=='ambiguous': artifact['events'].append({**event,'game_id':event['game_id']+'-duplicate'})
    if change=='unscheduled': event['scheduled']=False
    if change=='completed': event['completed']=True
    if change=='wrong_season': event['season']=20252026
    assert NHLGoalsModel(artifact).estimate(price) is None


def test_missing_forecast_reason_reaches_app_and_discord_without_raw_errors(portal):
    store, client = portal
    ordinary(store,research_probability=None,model_routing_reason='MODEL_INPUTS_UNAVAILABLE_OR_REJECTED',
             anomaly_reasons=['UNVERIFIED_EVENT_IDENTITY','SECRET_KEY_AND_RAW_EXCEPTION'],data_health='UNHEALTHY')
    sign_in(store,client)
    row=client.get('/v1/vip/board?sport=NBA').json()['rows'][0]
    assert row['probability_unavailable_reason']=='UNVERIFIED_EVENT_IDENTITY'
    assert 'Game identity' in row['probability_unavailable_message']
    message=summary(store,view='moneylines',sport='NBA')
    assert 'Game identity' in message['embed']['fields'][0]['value']
    assert 'SECRET_KEY' not in json.dumps(row)+json.dumps(message)


def test_routing_inventory_is_not_paid_coverage_or_model_approval(portal,monkeypatch):
    store,client=portal; ordinary(store)
    reg={'state':'READY','data':{'models':[{'sport':'basketball_nba','version':'synthetic',
         'status':'SHADOW_ONLY','supported_markets':['h2h'],'player_supported_markets':['player_points']}], 'errors':[]}}
    monkeypatch.setattr('jabazi.vip.model_cache.status',lambda loader:reg)
    forbidden=Mock(side_effect=AssertionError('No paid/provider requests in saved view'))
    monkeypatch.setattr('urllib.request.urlopen',forbidden)
    assert client.get('/v1/vip/model-routing').status_code==401
    sign_in(store,client)
    result=client.get('/v1/vip/model-routing').json()
    assert {s['sport'] for s in result['sports']}=={'NBA','NFL','NHL','MLB','CFB'}
    nba=next(s for s in result['sports'] if s['sport']=='NBA')
    assert nba['team_model_loaded'] and nba['player_models_loaded']==1
    points=next(m for m in nba['markets'] if m['market']=='player_points')
    assert points['model_loaded'] and points['state']=='NO_SAVED_QUOTES'
    assert points['forecast_rows']==0 and not points['approved_for_betting']
    ml=next(m for m in nba['markets'] if m['market']=='h2h')
    assert ml['state']=='FORECASTS_AVAILABLE' and ml['forecast_rows']==1
    assert next(s for s in result['sports'] if s['sport']=='CFB')['player_policy']=='POLICY_RESTRICTED'
    assert result['paid_requests_made']==0 and result['betting_enabled'] is False
    forbidden.assert_not_called()


def test_registry_refresh_is_not_reported_as_missing_models(portal):
    store,_=portal; ordinary(store,rows=[])
    report=routing_report(data.board(store),{'state':'REFRESHING','data':None})
    assert all(s['team_model_loaded'] is None for s in report['sports'])
    assert all(m['state']=='REGISTRY_REFRESHING' for s in report['sports'] for m in s['markets'])


def test_owner_model_status_exposes_same_saved_routing_counts(portal, monkeypatch):
    from unittest.mock import patch
    from jabazi.api import model_status_data
    store, _ = portal
    ordinary(store)
    monkeypatch.setattr('jabazi.api.platform_store', lambda: store)
    monkeypatch.setattr('jabazi.providers.player_features_live.LivePlayerFeatureCollector.provider_status', lambda self: {})
    with patch.object(store, 'close'):
        result = model_status_data()
    report = result['vip_model_routing']
    nba = next(s for s in report['sports'] if s['sport'] == 'NBA')
    assert nba['team_forecast_rows'] == 1 and nba['player_forecast_rows'] == 0
    assert nba['markets_with_forecasts'] == ['h2h']
    assert report['paid_requests_made'] == 0 and report['betting_enabled'] is False
    assert 'participant' not in json.dumps(report)

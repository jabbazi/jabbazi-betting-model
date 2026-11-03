"""Synthetic evidence for saved research display, never live model acceptance."""
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import Mock

import pytest
from test_member_portal import portal as _portal_fixture, sign_in
from jabazi.vip import data
from jabazi.vip.research import query_board, moneyline_board
from jabazi.discord_research_views import summary

portal = _portal_fixture


def ordinary(store, *, rows=None, games=None, healthy=True, **changes):
    now = datetime.now(UTC)
    row = {'sport': 'basketball_nba', 'event_id': 'nba-1', 'event': 'Away @ Home',
           'market': 'h2h', 'participant': None, 'selection': 'Home', 'line': None,
           'research_probability': .64, 'model_version': 'fixture-team-v1', 'model_stage': 'VALIDATING',
           'data_health': 'HEALTHY', 'status': 'WATCH', 'decimal_odds': 1.8, 'book': 'Fixture Book',
           'executable': True, 'price_time_utc': now.isoformat(), 'model_time_utc': now.isoformat(),
           'starts_at_utc': (now+timedelta(hours=3)).isoformat(), **changes}
    payload = {'rows': rows if rows is not None else [row], 'healthy': healthy, 'completed_at': now.isoformat()}
    if games is not None:
        payload['slate_events'] = games
    store.append('research_sheet', 'latest_scan', payload)
    return row


def paid(store, *, sport='NHL', count=61, rows=None, **changes):
    now = datetime.now(UTC)
    row = {'sport': 'icehockey_nhl' if sport == 'NHL' else 'basketball_nba',
           'event_id': 'nhl-1' if sport == 'NHL' else 'nba-1', 'event': 'Away @ Home',
           'participant': 'Fixture Player', 'market': 'player_shots_on_goal', 'selection': 'over',
           'line': '2.5', 'settlement': 'OVER_UNDER', 'model_probability': .62,
           'model_version': 'fixture-player-v1', 'model_stage': 'VALIDATING',
           'model_time': now.isoformat(), 'source_timestamp': (now-timedelta(minutes=4)).isoformat(),
           'starts_at': (now+timedelta(hours=3)).isoformat(), 'best_decimal': 1.91,
           'best_sportsbook': 'Fixture Book', 'probability_basis': 'FITTED_JABBAZI_MODEL',
           'projected_mean': 3.4, 'feature_snapshot_id': 'PRIVATE_FEATURE_ID',
           'source_crosswalk_sha256': 'PRIVATE_MANIFEST_DIGEST', **changes}
    items = rows if rows is not None else [{**row, 'participant': f'Fixture Player {i:03}',
                                          'selection': 'under' if i % 2 else 'over'} for i in range(count)]
    store.append('paid_player_scan', now.date().isoformat(), {'slate_date': now.date().isoformat(),
                 'observed_at': now.isoformat(), 'status': 'PARTIAL', 'sports': {
                     sport: {'coverage': 'FULL', 'research_rows': items, 'model_probability_rows': len(items)}}})
    return row


def test_all_paid_props_reach_board_search_detail_and_page_two(portal):
    store, client = portal
    paid(store)
    sign_in(store, client)
    one = client.get('/v1/vip/board?sport=NHL&family=props').json()
    assert one['total'] == 61 and len(one['rows']) == 50 and one['next'] == 50
    two = client.get('/v1/vip/board?sport=NHL&family=props&offset=50').json()
    assert len(two['rows']) == 11 and two['next'] is None
    assert len({r['id'] for r in one['rows']+two['rows']}) == 61
    r = one['rows'][0]
    assert r['model_probability'] == .62 and r['model_fresh']
    assert r['projected_mean'] == 3.4 and r['book'] == 'Fixture Book'
    assert not r['approved_for_betting'] and r['ev'] is None
    assert client.get('/v1/vip/detail/'+r['id']).json()['row'] == r
    assert client.get('/v1/vip/search?q=Fixture').json()['total'] == 61
    for secret in ('PRIVATE_FEATURE_ID', 'PRIVATE_MANIFEST_DIGEST'):
        assert secret not in json.dumps(one)
    under = client.get('/v1/vip/board?sport=NHL&family=props&side=under').json()
    assert under['total'] == 30 and all(r['selection'] == 'under' for r in under['rows'])
    assert client.get('/v1/vip/board?sport=NHL&family=props&book=Fixture%20Book').json()['total'] == 61
    assert client.get('/v1/vip/player-probabilities?sport=NHL').json()['model_estimate_rows'] == 61


def test_paid_player_other_lines_markets_and_filters_are_not_hidden(portal):
    store, client = portal
    r = paid(store, count=0)
    paid(store, rows=[r, {**r, 'line': '3.5', 'selection': 'under'},
                      {**r, 'market': 'player_goals', 'line': '0.5'}])
    sign_in(store, client)
    board = client.get('/v1/vip/board?family=props&sport=NHL&player=Fixture%20Player').json()
    assert board['total'] == 3
    assert {r['market'] for r in board['rows']} == {'player_shots_on_goal', 'player_goals'}
    assert any(m['value'] == 'player_total_saves' and m['count'] == 0 for m in board['facets']['markets'])
    missing = client.get('/v1/vip/board?family=props&sport=NHL&market=player_total_saves').json()
    assert missing['rows'] == [] and missing['empty_reason'] == 'NO_FILTER_MATCHES'
    assert missing['scope_total'] == 3


def test_validating_moneyline_survives_old_price_with_no_current_ev(portal):
    store, client = portal
    r = ordinary(store, price_time_utc=(datetime.now(UTC)-timedelta(minutes=10)).isoformat())
    ordinary(store, rows=[r], games=[{**r}, {**r, 'event_id': 'no-model', 'event': 'Scheduled @ No Forecast'}])
    sign_in(store, client)
    report = client.get('/v1/vip/moneylines?sport=NBA').json()
    assert report['total'] == 2
    forecast, missing = report['games']
    assert forecast['predicted_winner'] == 'Home' and forecast['model_probability'] == .64
    assert forecast['model']['ev'] is None and forecast['model']['edge'] is None
    assert not forecast['model']['fresh'] and forecast['model']['model_fresh']
    assert missing['predicted_winner'] is None and 'No saved' in missing['reason']
    detail = client.get('/v1/vip/matchup/NBA/nba-1').json()
    assert detail['projection']['source'] == 'INDEPENDENT MODEL'
    assert detail['projection']['model_probability'] == .64
    assert client.get('/v1/vip/matchup/NBA/no-model').json()['state'] == 'NO_MODEL_FORECAST'
    assert client.get('/v1/vip/moneylines?sport=NBA&sort=value').json()['games'] == []


@pytest.mark.parametrize('stage', ['SHADOW_ONLY', 'VALIDATING', 'LIMITED_LIVE', 'PRODUCTION_APPROVED'])
def test_safe_model_stages_visible_without_promotion(portal, stage):
    store, client = portal
    ordinary(store, model_stage=stage)
    sign_in(store, client)
    row = client.get('/v1/vip/moneylines?sport=NBA').json()['games'][0]['model']
    assert row['model_probability'] == .64 and row['model_stage'] == stage
    assert row['approved_for_betting'] is False


@pytest.mark.parametrize('change', [{'status': 'QUARANTINED'}, {'anomaly_state': 'EXTREME_DISAGREEMENT'},
                                   {'data_health': 'UNKNOWN'}, {'model_version': None},
                                   {'model_stage': 'UNAVAILABLE'}, {'research_probability': True}])
def test_unsafe_or_unproven_forecast_never_becomes_model_winner(portal, change):
    store, client = portal
    ordinary(store, **change)
    sign_in(store, client)
    game = client.get('/v1/vip/moneylines?sport=NBA').json()['games'][0]
    assert game['predicted_winner'] is None and game['model_probability'] is None


def test_partial_feed_does_not_erase_independent_team_model(portal):
    store, client = portal
    ordinary(store, healthy=False)
    sign_in(store, client)
    result = client.get('/v1/vip/moneylines?sport=NBA').json()
    assert result['games'][0]['model_probability'] == .64
    assert result['games'][0]['model']['ev'] is None


def test_one_sport_paid_refresh_preserves_other_saved_sport(portal):
    store, _ = portal
    paid(store, sport='NHL', count=1)
    paid(store, sport='NBA', count=1, market='player_points')
    b = data.board(store)
    assert {r['sport'] for r in b['rows']} == {'NBA', 'NHL'}
    assert len(b['sources']) == 2


def test_moved_or_cancelled_event_blocks_prior_paid_forecast(portal):
    store, _ = portal
    r = paid(store, count=1)
    schedule = {'sport': 'icehockey_nhl', 'event_id': 'nhl-1', 'event': 'Away @ Home',
                'starts_at': (datetime.now(UTC)+timedelta(hours=4)).isoformat()}
    ordinary(store, rows=[], games=[schedule])
    assert not data.board(store)['rows']
    ordinary(store, rows=[], games=[{**schedule, 'starts_at': r['starts_at'], 'event_status': 'cancelled'}])
    assert not data.board(store)['rows']


def test_stale_model_and_other_date_never_reappear_from_paid_archive(portal):
    store, _ = portal
    paid(store, count=1, model_time=(datetime.now(UTC)-timedelta(hours=2)).isoformat())
    assert data.board(store)['rows'] == []
    paid(store, count=1, starts_at=(datetime.now(UTC)+timedelta(days=1)).isoformat())
    assert data.board(store)['rows'] == []


def test_integer_push_line_does_not_acquire_binary_value(portal):
    store, client = portal
    ordinary(store, market='player_points', participant='Fixture', selection='Over', line='20')
    sign_in(store, client)
    row = client.get('/v1/vip/board?family=props').json()['rows'][0]
    assert row['model_probability'] == .64
    assert row['ev'] is None and row['fair_decimal'] is None and row['play_to_decimal'] is None


def test_saved_lab_route_is_private_allowlisted_paginated_and_free(portal, monkeypatch):
    store, client = portal
    probe = Mock(side_effect=AssertionError('View must not fetch provider'))
    monkeypatch.setattr('jabazi.vip.paid_models.read_paid_player_models', probe)
    assert client.get('/v1/vip/paid-player-models?sport=NBA').status_code == 401
    now = datetime.now(UTC)
    store.append('paid_lab_signal_snapshot', 'NBA', {'slate_date': now.date().isoformat(),
        'state': 'RESEARCH_ONLY', 'coverage_complete': True, 'observed_at': now.isoformat(),
        'rows': [{'id': i, 'sport': 'NBA', 'player_name': f'Fixture {i}', 'model_signal_value': .9,
                  'provider_secret': 'DO_NOT_LEAK', 'model_hit_probability': .99} for i in range(55)]})
    sign_in(store, client)
    value = client.get('/v1/vip/paid-player-models?sport=NBA').json()
    assert value['total'] == 55 and value['next'] == 50
    assert value['rows'][0]['model_hit_probability'] is None
    assert 'DO_NOT_LEAK' not in json.dumps(value)
    assert len(client.get('/v1/vip/paid-player-models?sport=NBA&offset=50').json()['rows']) == 5
    assert client.get('/v1/vip/paid-player-models?sport=NHL').json()['reason'] == 'LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED'
    assert not probe.called


def test_discord_summary_matches_canonical_vip_records_and_cannot_ping(portal):
    store, _ = portal
    paid(store, count=0)
    r = paid(store, count=1, participant='@everyone **Fixture**')
    paid(store, rows=[{**r, 'participant': '@everyone **Fixture**'}])
    board = data.board(store)
    before = len(store.list_records())
    out = summary(store, view='props', sport='NHL')
    assert out['row_ids'] == [board['rows'][0]['id']]
    assert not out['approved_for_betting'] and out['paid_requests_made'] == 0
    assert '@everyone' not in json.dumps(out['embed'])
    assert '62.0%' in out['embed']['fields'][0]['value']
    assert len(store.list_records()) == before
    assert out['snapshot_ids'] == [board['sources'][0]['snapshot_id']]


def test_discord_moneyline_and_vip_agree_and_page_counts_are_explicit(portal):
    store, _ = portal
    ordinary(store)
    b = data.board(store)
    web = moneyline_board(b, sport='NBA')['games'][0]['model']
    discord = summary(store, view='moneylines', sport='NBA')
    assert discord['row_ids'] == [web['id']]
    assert '64.0%' in discord['embed']['fields'][0]['value']
    paid(store)
    first = summary(store, view='props', sport='NHL')
    second = summary(store, view='props', sport='NHL', page=2)
    assert first['total'] == second['total'] == 61 and first['next_page'] == 2
    assert set(first['row_ids']).isdisjoint(second['row_ids'])


def test_board_projection_requires_actual_mean_not_line(portal):
    store, _ = portal
    ordinary(store, market='player_points', participant='Fixture', selection='Over', line='21.5')
    row = query_board(data.board(store), family='props')['rows'][0]
    assert row['projected_mean'] is None


def test_discord_top10_matches_vip_model_ranking_and_deduplicates_lines(portal):
    store, client = portal
    row = paid(store, count=0)
    paid(store, rows=[{**row, 'participant': 'One', 'model_probability': .62},
                      {**row, 'participant': 'One', 'line': '3.5', 'model_probability': .58},
                      {**row, 'participant': 'Two', 'model_probability': .61}])
    sign_in(store, client)
    ranking = client.get('/v1/vip/rankings?sport=NHL').json()['player_markets']['player_shots_on_goal']
    message = summary(store, view='top10', sport='NHL', market='player_shots_on_goal')
    assert len(ranking) == message['total'] == 2
    assert message['row_ids'] == [r['id'] for r in ranking]
    assert message['next_page'] is None
    assert message['paid_requests_made'] == 0


def test_malformed_paid_record_does_not_blank_other_player_or_team_rows(portal):
    store, client = portal
    ordinary(store)
    row = paid(store, count=0)
    paid(store, rows=[row, {**row, 'participant': 'Bad', 'book_prices': 'not-a-dict'}])
    sign_in(store, client)
    result = client.get('/v1/vip/board').json()
    assert len(result['rows']) == 2
    assert result['paid_coverage']['NHL']['malformed_research_rows'] == 1
    assert result['partial']
    assert client.get('/v1/vip/moneylines?sport=NBA').json()['games'][0]['predicted_winner'] == 'Home'


def test_research_endpoints_require_member_session(portal):
    _, client = portal
    for path in ('moneylines?sport=NBA', 'board?family=props', 'player-probabilities?sport=NHL',
                 'paid-player-models?sport=NBA'):
        assert client.get('/v1/vip/'+path).status_code == 401


def test_new_discord_commands_recheck_membership_and_never_ping(portal):
    import asyncio
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock, patch
    import discord
    from jabazi.discord_bot import build_client, BotConfig

    store, _ = portal
    ordinary(store)
    paid(store, count=2)

    async def run():
        bot = build_client(BotConfig(1, 2, 3, 4, frozenset()), store)
        async def sync(tree, *, guild):
            return tree.get_commands(guild=guild)
        with patch.object(discord.app_commands.CommandTree, 'sync', sync):
            await bot._async_setup_hook()
            await bot.setup_hook()
        member = NS(id=5, roles=[NS(id=8, name='JABBAZI VIP')])
        interaction = NS(guild_id=1, user=NS(id=5, roles=[]), guild=NS(fetch_member=AsyncMock(return_value=member)),
                         response=NS(defer=AsyncMock(), send_message=AsyncMock()), followup=NS(send=AsyncMock()))
        for command, sport in [('props', 'NHL'), ('moneylines', 'NBA'), ('top10', 'NHL')]:
            await bot.tree.get_command(command, guild=discord.Object(id=1)).callback(interaction, sport=sport)
            sent = interaction.followup.send.call_args
            assert sent.kwargs['ephemeral'] is True
            assert sent.kwargs['allowed_mentions'].to_dict() == {'parse': []}
            assert 'sport='+sport in sent.args[0] and 'access=' in sent.args[0]
            assert '&date=' in sent.args[0]
            assert sent.kwargs['embed'].description.split(' · ')[0] in sent.args[0]
            assert sent.kwargs['embed'].fields
            assert 'not official picks' in sent.kwargs['embed'].description
        tickets = len(store.list_records('member_ticket', 100))
        interaction.guild.fetch_member.return_value = NS(id=5, roles=[])
        for command in ('props', 'moneylines', 'top10'):
            await bot.tree.get_command(command, guild=discord.Object(id=1)).callback(interaction)
            assert 'access=' not in str(interaction.followup.send.call_args)
        assert len(store.list_records('member_ticket', 100)) == tickets
        # With no candidates, official publishing does not probe a nonexistent channel.
        with patch.object(bot, 'checked_channel', AsyncMock(side_effect=AssertionError('unused channel'))) as channel:
            await bot.publish_official_picks_once()
            channel.assert_not_awaited()
        await bot.close()
    asyncio.run(run())


def test_same_player_line_at_two_books_remains_browsable(portal):
    store, client = portal
    row = paid(store, count=0)
    paid(store, rows=[{**row, 'best_sportsbook': 'Fixture A', 'best_decimal': 1.80},
                      {**row, 'best_sportsbook': 'Fixture B', 'best_decimal': 1.95}])
    sign_in(store, client)
    all_rows = client.get('/v1/vip/board?family=props&sport=NHL').json()['rows']
    assert len(all_rows) == 2
    assert len({r['id'] for r in all_rows}) == 2
    for row in all_rows:
        detail = client.get('/v1/vip/detail/' + row['id']).json()['row']
        assert detail['book'] == row['book'] and detail['decimal'] == row['decimal']
    filtered = client.get('/v1/vip/board?family=props&sport=NHL&book=Fixture%20B').json()
    assert filtered['total'] == 1 and filtered['rows'][0]['book'] == 'Fixture B'
    # A ranked summary is still one player/stat, not two artificial opportunities.
    ranked = client.get('/v1/vip/rankings?sport=NHL').json()['player_markets']['player_shots_on_goal']
    assert len(ranked) == 1


def test_global_alias_search_keeps_cross_sport_results(portal):
    store, client = portal
    row = ordinary(store)
    ordinary(store, rows=[row, {**row, 'sport': 'baseball_mlb', 'event_id': 'mlb-1',
              'participant': 'Fixture Judge', 'market': 'batter_home_runs',
              'selection': 'Over', 'line': '.5'}])
    sign_in(store, client)
    result = client.get('/v1/vip/board?q=Judge%20HR').json()
    assert result['total'] == 1 and result['rows'][0]['sport'] == 'MLB'
    assert client.get('/v1/vip/board?q=Judge%20HR&sport=NBA').json()['total'] == 0


def test_discord_page_has_explicit_matching_slate_date(portal):
    store, _ = portal
    paid(store, count=12)
    report = summary(store, view='props', sport='NHL')
    assert report['slate_date'] in report['embed']['description']
    assert report['next_page'] == 2
    assert '/props sport:NHL page:2' in report['embed']['description']

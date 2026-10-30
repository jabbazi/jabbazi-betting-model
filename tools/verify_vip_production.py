"""Read-only production acceptance using a freshly verified owner Discord identity.

Tokens stay in process memory and are never printed. No fixtures, wagers,
watchlist mutations, permission changes, or notifications are created.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import httpx

from jabazi.member_access import issue_ticket, portal_origin
from jabazi.persistence.store import Store


def main():
    guild = os.environ['JABBAZI_DISCORD_GUILD_ID']
    owner = os.environ['JABBAZI_DISCORD_OWNER_ID']
    store = Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'])
    checks = {'verification_version': 9}
    try:
        with httpx.Client(base_url='https://discord.com/api/v10', headers={'Authorization': 'Bot ' + os.environ['JABBAZI_DISCORD_BOT_TOKEN']}, timeout=20) as discord:
            info = discord.get(f'/guilds/{guild}')
            member = discord.get(f'/guilds/{guild}/members/{owner}')
            if info.status_code != 200 or member.status_code != 200 or str(info.json()['owner_id']) != owner:
                raise ValueError('Owner identity verification failed')
        origin = portal_origin()
        with httpx.Client(base_url=origin, timeout=12) as client:
            checks['anonymous_blocked'] = client.get('/v1/vip/home').status_code == 401
            ticket = issue_ticket(store, guild=guild, member=owner, authorized=True)
            signed = client.post('/v1/member/session', json={'ticket': ticket}, headers={'Origin': origin})
            checks['sign_in_http'] = signed.status_code
            if signed.status_code == 200:
                try:
                    for path in ('me', 'home', 'today', 'matchups', 'playoftheday', 'board?sport=MLB', 'board?sport=NFL', 'board?sport=CFB', 'board?sport=NBA', 'board?sport=NHL', 'board?family=props', 'search?q=KC', 'sheets', 'top10?kind=hr', 'top10?kind=td', 'rankings?sport=NFL', 'rankings?sport=NBA', 'rankings?sport=NHL', 'rankings?sport=MLB', 'watchlist', 'performance', 'models', 'admin'):
                        started = time.monotonic()
                        try:
                            result = client.get('/v1/vip/' + path)
                            checks[path] = {'http': result.status_code, 'elapsed_ms': round((time.monotonic() - started) * 1000)}
                            if result.status_code == 200:
                                body = result.json()
                                if 'rows' in body:
                                    checks[path]['rows'] = len(body['rows'])
                                    if path.startswith('board'):
                                        from jabazi.daily_scope import eligible_today
                                        from datetime import date
                                        checks[path]['slate_date'] = body.get('date')
                                        checks[path]['today_only'] = all(eligible_today(row, slate_date=date.fromisoformat(body['date'])) for row in body['rows'])
                                        if path == 'board?family=props':
                                            checks[path]['props_only'] = all(str(row.get('market', '')).startswith(('player_', 'pitcher_', 'batter_')) for row in body['rows'])
                                        if not checks[path]['today_only']:
                                            checks[path]['scope_error'] = 'OUT_OF_DATE_EVENT'
                                if path.startswith('rankings'):
                                    from jabazi.vip.rankings import current
                                    from datetime import UTC, date, datetime
                                    now = datetime.now(UTC)
                                    ranked = [r for key in ('moneyline_likely','moneyline_value','anytime_td','receiving_overs') for r in body.get(key, [])]
                                    checks[path]['today_only'] = all(current(r, now, date.fromisoformat(body['date'])) for r in ranked)
                                    checks[path]['ranked_rows'] = len(ranked)
                                    checks[path]['web_research_state'] = body.get('web_research_state')
                                if path == 'admin':
                                    checks[path]['owner_health_available'] = bool(body.get('health', {}).get('api', {}).get('commit')) if body.get('health') else False
                                    checks[path]['health_queries_complete'] = body.get('health') is not None and not body['health'].get('query_failures')
                                if 'state' in body:
                                    checks[path]['state'] = body['state']
                        except httpx.HTTPError as exc:
                            checks[path] = {'http': None, 'elapsed_ms': round((time.monotonic() - started) * 1000), 'error': type(exc).__name__}
                    try:
                        from urllib.parse import quote
                        games = client.get('/v1/vip/matchups').json().get('games', [])
                        checks['matchup_games_observed'] = len(games)
                        if games:
                            game = games[0]
                            sport = quote(str(game['sport']), safe='')
                            event = quote(str(game['event_id']), safe='')
                            for label, path in (
                                ('matchup_detail', f'/v1/vip/matchup/{sport}/{event}'),
                                ('game_sim', f'/v1/vip/sim/{sport}/{event}?spread_line=0&total_line=40'),
                            ):
                                started = time.monotonic()
                                try:
                                    result = client.get(path)
                                    checks[label] = {'http': result.status_code, 'elapsed_ms': round((time.monotonic()-started)*1000)}
                                    if result.status_code == 200:
                                        checks[label]['state'] = result.json().get('state', 'RESEARCH')
                                        checks[label]['model_available'] = bool(result.json().get('summary')) if label == 'game_sim' else bool(result.json().get('projection', {}).get('model_probability'))
                                except httpx.HTTPError as exc:
                                    checks[label] = {'http': None, 'error': type(exc).__name__}
                            graphic = client.get(f'/v1/vip/graphic/{sport}/{event}')
                            checks['matchup_graphic'] = {'http': graphic.status_code,
                                'png_signature': graphic.content.startswith(b'\x89PNG\r\n\x1a\n')}
                            nfl = next((g for g in games if g['sport'] == 'NFL'), None)
                            if nfl:
                                ft = client.get('/v1/vip/firsttd/'+quote(str(nfl['event_id']), safe=''))
                                checks['firsttd'] = {'http': ft.status_code,
                                    'state': ft.json().get('state'), 'rankings': len(ft.json().get('players', []))}
                            brand = client.get('/vip/jabbazi-approved.png')
                            checks['approved_logo'] = {'http': brand.status_code,
                                'png_signature': brand.content.startswith(b'\x89PNG\r\n\x1a\n')}
                        else:
                            checks['matchup_detail'] = {'skipped': 'NO_ELIGIBLE_GAMES'}
                            checks['game_sim'] = {'skipped': 'NO_ELIGIBLE_GAMES'}
                    except (ValueError, KeyError, TypeError) as exc:
                        checks['matchup_smoke_error'] = type(exc).__name__
                    checks['ticket_replay_rejected'] = client.post('/v1/member/session', json={'ticket': ticket}, headers={'Origin': origin}).status_code == 401
                finally:
                    checks['logout_http'] = client.post('/v1/member/logout', headers={'Origin': origin}).status_code
                checks['logged_out_blocked'] = client.get('/v1/vip/home').status_code == 401
            checks['scope'] = 'AUTH_AND_ENDPOINT_TRANSPORT_ONLY_NOT_MODEL_VALIDATION'
            checks['status'] = 'VERIFIED' if checks.get('anonymous_blocked') and checks.get('ticket_replay_rejected') and checks.get('sign_in_http') == 200 and checks.get('logout_http') == 200 and checks.get('logged_out_blocked') and all((v.get('http') == 200 or v.get('skipped') == 'NO_ELIGIBLE_GAMES') and v.get('today_only', True) and v.get('props_only', True) and v.get('png_signature', True) and v.get('owner_health_available', True) and v.get('health_queries_complete', True) for v in checks.values() if isinstance(v, dict)) else 'INCOMPLETE'
    except Exception as exc:  # noqa: BLE001 -- acceptance boundary records only the redacted error class
        checks.update(status='UNAVAILABLE', error=type(exc).__name__)
    finally:
        store.append('vip_acceptance', 'terminal-v1', checks)
        store.close()
    print('VIP_ACCEPTANCE_VERIFICATION ' + json.dumps(checks), flush=True)
    return 0 if checks['status'] == 'VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())

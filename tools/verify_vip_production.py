"""Read-only production acceptance using a freshly verified owner Discord identity.

Tokens stay in process memory and are never printed. No fixtures, wagers,
watchlist mutations, permission changes, or notifications are created.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import httpx

from jabazi.member_access import issue_ticket, portal_origin
from jabazi.persistence.store import Store


def main():
    guild = os.environ['JABBAZI_DISCORD_GUILD_ID']
    owner = os.environ['JABBAZI_DISCORD_OWNER_ID']
    store = Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'])
    checks = {}
    try:
        with httpx.Client(base_url='https://discord.com/api/v10', headers={'Authorization': 'Bot ' + os.environ['JABBAZI_DISCORD_BOT_TOKEN']}, timeout=20) as discord:
            info = discord.get(f'/guilds/{guild}')
            member = discord.get(f'/guilds/{guild}/members/{owner}')
            if info.status_code != 200 or member.status_code != 200 or str(info.json()['owner_id']) != owner:
                raise ValueError('Owner identity verification failed')
        origin = portal_origin()
        with httpx.Client(base_url=origin, timeout=45) as client:
            checks['anonymous_blocked'] = client.get('/v1/vip/home').status_code == 401
            ticket = issue_ticket(store, guild=guild, member=owner, authorized=True)
            signed = client.post('/v1/member/session', json={'ticket': ticket}, headers={'Origin': origin})
            checks['sign_in_http'] = signed.status_code
            if signed.status_code == 200:
                try:
                    for path in ('me', 'home', 'board?sport=MLB', 'board?sport=NFL', 'board?sport=CFB', 'search?q=KC', 'sheets', 'top10?kind=hr', 'top10?kind=td', 'watchlist', 'performance', 'models', 'admin'):
                        result = client.get('/v1/vip/' + path)
                        checks[path] = {'http': result.status_code}
                        if result.status_code == 200:
                            body = result.json()
                            if 'rows' in body:
                                checks[path]['rows'] = len(body['rows'])
                            if 'state' in body:
                                checks[path]['state'] = body['state']
                    checks['ticket_replay_rejected'] = client.post('/v1/member/session', json={'ticket': ticket}, headers={'Origin': origin}).status_code == 401
                finally:
                    checks['logout_http'] = client.post('/v1/member/logout', headers={'Origin': origin}).status_code
                checks['logged_out_blocked'] = client.get('/v1/vip/home').status_code == 401
            checks['status'] = 'VERIFIED' if checks.get('anonymous_blocked') and checks.get('ticket_replay_rejected') and checks.get('sign_in_http') == 200 and checks.get('logout_http') == 200 and checks.get('logged_out_blocked') and all(v.get('http') == 200 for v in checks.values() if isinstance(v, dict)) else 'INCOMPLETE'
    except Exception as exc:  # noqa: BLE001 -- acceptance boundary records only the redacted error class
        checks.update(status='UNAVAILABLE', error=type(exc).__name__)
    finally:
        store.append('vip_acceptance', 'terminal-v1', checks)
        store.close()
    print('VIP_ACCEPTANCE_VERIFICATION ' + json.dumps(checks), flush=True)
    return 0 if checks['status'] == 'VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())

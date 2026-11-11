"""Read-only status destination preflight. Never sends or changes permissions."""
import argparse
from dataclasses import replace
import json
import os

import httpx

from jabazi.discord_access import is_staff_name, is_vip_name
from jabazi.discord_bot import BotConfig, validate_target


def inspect_target(http, config, *, status_channel=None, paid_roles=()):
    report = {'status': 'BLOCKED', 'checks': [], 'message_sent': False,
              'configuration_changed': False}

    def get(label, path):
        response = http.get(path)
        document = response.json()
        report['checks'].append({'resource': label, 'http': response.status_code,
                                'code': document.get('code') if isinstance(document, dict) else None})
        if response.status_code != 200:
            raise ValueError('DISCORD_RESOURCE_UNAVAILABLE')
        return document

    try:
        bot = get('bot', '/users/@me')
        guild = get('guild', f'/guilds/{config.guild}')
        if int(guild['owner_id']) != config.owner:
            raise ValueError('OWNER_MISMATCH')
        member = get('bot_member', f'/guilds/{config.guild}/members/{bot["id"]}')
        roles = get('roles', f'/guilds/{config.guild}/roles')
        target = status_channel or config.status_channel
        channel = get('status_channel', f'/channels/{target}')
        allowed = tuple(int(r) for r in member.get('roles', [])) + tuple(
            int(r['id']) for r in roles if is_vip_name(r.get('name')) or is_staff_name(r.get('name'))
        ) + tuple(int(r) for r in paid_roles)
        validate_target(channel, replace(config, status_channel=target), int(bot['id']), allowed)
        report.update(status='TARGET_VALIDATED', target_channel=str(target),
                      replacement=target != config.status_channel)
    except (ValueError, KeyError, TypeError, httpx.HTTPError):
        # No upstream exception body, URL, credentials or member data escapes.
        report['reason'] = 'RESOURCE_OR_PRIVACY_CHECK_FAILED'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status-channel', type=int)
    args = parser.parse_args(argv)
    try:
        # Read the existing role gate without importing/starting the API or scanner.
        from sqlalchemy import text
        from jabazi.persistence.store import Store
        store = Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'])
        try:
            with store.engine.connect() as conn:
                conn.execute(text('SET TRANSACTION READ ONLY'))
                conn.execute(text('SET LOCAL statement_timeout=10000'))
                gate = conn.execute(text("SELECT payload FROM platform_events WHERE kind='discord_rules_config' AND entity='rules-gate' ORDER BY occurred_at DESC LIMIT 1")).scalar()
            paid = ()
            if gate and gate.get('status') == 'ACTIVE':
                paid = tuple((gate.get('paid_roles') or {'legacy': gate['paid_role']}).values())
        finally:
            store.close()
        with httpx.Client(base_url='https://discord.com/api/v10', timeout=15,
                          headers={'Authorization': 'Bot '+os.environ['JABBAZI_DISCORD_BOT_TOKEN']}) as http:
            report = inspect_target(http, BotConfig.from_env(),
                                    status_channel=args.status_channel, paid_roles=paid)
    except Exception:
        report = {'status': 'BLOCKED', 'reason': 'LOCAL_CONFIGURATION_UNAVAILABLE',
                  'message_sent': False, 'configuration_changed': False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'TARGET_VALIDATED' else 2


if __name__ == '__main__':
    raise SystemExit(main())

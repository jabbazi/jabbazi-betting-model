"""Durable, backed-up onboarding intros with verified pins and safe mentions."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .discord_migration import channel_name, request
from .persistence.store import digest

MARKER = 'JABBAZI_SETUP_V'


def read_pins(http, channel):
    rows = []
    before = ''
    while True:
        page = request(http, 'GET', f'/channels/{channel}/messages/pins?limit=50{before}', 'READ_PINS')
        items = page.get('items', [])
        rows.extend(item['message'] for item in items)
        if not page.get('has_more') or not items:
            return rows
        before = '&before=' + items[-1]['pinned_at']


def introduction_snapshot(http, channel, bot):
    pins = read_pins(http, channel)
    recent = request(http, 'GET', f'/channels/{channel}/messages?limit=50', 'READ_INTRODUCTIONS')
    # Preserve only onboarding text; ordinary member messages/private links are
    # not copied into backups. Pin metadata is enough to restore pin choices.
    guides = {str(m['id']): m for m in pins + recent if str(m.get('author', {}).get('id')) == str(bot) and MARKER in m.get('content', '')}
    return {'channel_id': str(channel), 'pins': [{'id': str(m['id']), 'author_id': str(m.get('author', {}).get('id', ''))} for m in pins],
            'introductions': [{'id': str(m['id']), 'content': re.sub(r'(?:https?://\S+)?(?:#access=|[?&]token=)\S+', '[private link redacted]', m.get('content', '')), 'pinned': bool(m.get('pinned'))} for m in guides.values()]}


def seed(http, store, *, guild, owner, apply=False):
    info = request(http, 'GET', f'/guilds/{guild}', 'READ_GUILD')
    if str(info['owner_id']) != str(owner):
        raise ValueError('Configured Discord owner mismatch')
    bot = request(http, 'GET', '/users/@me', 'READ_BOT')['id']
    channels = request(http, 'GET', f'/guilds/{guild}/channels', 'READ_CHANNELS')
    bp = json.loads(Path('docs/discord/server_blueprint.json').read_text())
    content = json.loads(Path('docs/discord/seed_content.json').read_text())
    parents = {str(c['id']): c['name'] for c in channels if c['type'] == 4}
    expected = {n: c['name'] for c in bp['categories'] for n in c['channels']}
    by_name = {channel_name(c['name']): c for c in channels if c['type'] == 0 and parents.get(str(c.get('parent_id'))) == expected.get(channel_name(c['name']))}
    plan = []
    for name, message in content.items():
        channel = by_name.get(name)
        if channel is None:
            plan.append({'channel': name, 'status': 'MISSING_CHANNEL'})
            continue
        cid = str(channel['id'])
        try:
            def mention(match):
                if match[1] not in by_name:
                    raise ValueError('Missing onboarding link destination')
                return '<#' + str(by_name[match[1]]['id']) + '>'
            message = re.sub(r'#([a-z][a-z0-9-]+)', mention, message)
            snapshot = introduction_snapshot(http, cid, bot)
            previous = None
            saved = store.list_records('discord_intro_receipt', 1, entity=cid)
            if saved:
                mid = saved[0]['payload']['message_id']
                response = http.get(f'/channels/{cid}/messages/{mid}')
                if response.status_code == 200:
                    row = response.json()
                    if str(row.get('author', {}).get('id')) != str(bot) or MARKER not in row.get('content', ''):
                        raise ValueError('Saved introduction ownership mismatch')
                    previous = row
                elif response.status_code != 404:
                    raise RuntimeError('Saved introduction lookup failed')
            if previous is None and snapshot['introductions']:
                previous = sorted(snapshot['introductions'], key=lambda r: int(r['id']))[0]
            if not apply:
                plan.append({'channel': name, 'status': 'WOULD_UPDATE' if previous else 'WOULD_POST'})
                continue
            key = digest(['discord_intro_backup', cid, snapshot])
            store.append('discord_intro_backup', cid, snapshot, key)
            if not any(r['id'] == key for r in store.list_records('discord_intro_backup', 100, entity=cid)):
                raise RuntimeError('Introduction backup readback failed')
            payload = {'content': message, 'allowed_mentions': {'parse': []}}
            if previous:
                mid = str(previous['id'])
                if previous.get('content') != message:
                    request(http, 'PATCH', f'/channels/{cid}/messages/{mid}', 'UPDATE_INTRODUCTION', json=payload)
            else:
                claim = digest(['discord_intro_post', cid, 'v4'])
                if not store.append('discord_intro_post', cid, {'status': 'CLAIMED'}, claim):
                    raise RuntimeError('Ambiguous introduction delivery requires review')
                posted = request(http, 'POST', f'/channels/{cid}/messages', 'POST_INTRODUCTION', json={**payload, 'nonce': claim[:24], 'enforce_nonce': True})
                mid = str(posted['id'])
            store.append('discord_intro_receipt', cid, {'message_id': mid}, digest(['discord_intro_receipt', cid, mid]))
            row = request(http, 'GET', f'/channels/{cid}/messages/{mid}', 'VERIFY_INTRODUCTION')
            if row.get('content') != message:
                raise RuntimeError('Introduction content verification failed')
            status = 'PINNED'
            try:
                if not row.get('pinned'):
                    request(http, 'PUT', f'/channels/{cid}/messages/pins/{mid}', 'PIN_INTRODUCTION')
                verified_pins = read_pins(http, cid)
                if not any(str(m['id']) == mid for m in verified_pins):
                    raise RuntimeError('Pin readback failed')
                # Retain history and unrelated pins; remove only obsolete bot guides.
                for old in verified_pins:
                    if str(old['id']) != mid and str(old.get('author', {}).get('id')) == str(bot) and MARKER in old.get('content', ''):
                        request(http, 'DELETE', f'/channels/{cid}/messages/pins/{old["id"]}', 'UNPIN_OBSOLETE_INTRODUCTION')
            except RuntimeError:
                status = 'INTRO_VERIFIED_PIN_UNAVAILABLE'
            plan.append({'channel': name, 'channel_id': cid, 'message_id': mid, 'status': status})
        except Exception as exc:
            # No message bodies, secrets or SDK exception strings in logs.
            plan.append({'channel': name, 'channel_id': cid, 'status': 'UNAVAILABLE', 'error': type(exc).__name__})
    return {'mode': 'APPLIED' if apply else 'DRY_RUN', 'plan': plan}

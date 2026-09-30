"""Private member review space and sanitized, occasional public research previews."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .discord_access import vip_role_ids
from .discord_migration import VIEW, STAFF_NAMES, channel_name, effective_permissions, request
from .discord_sheets import latest_sheet
from .persistence.store import digest

REVIEW_NAME = '🧠 Member bet reviews'
REVIEW_TEXT = ('🧠 **MEMBER BET REVIEWS**\n'
               'Want a second look? Post:\n'
               '• Sport, matchup and start time\n• Sportsbook, exact market/line and odds (with quote time)\n'
               '• Your reasoning and related bets/exposure\n\n'
               'Hide account details and personal information in screenshots. '
               'Community feedback is not an official JABBAZI recommendation or approval; '
               'a response is not guaranteed. Official plays stay in the Main Card. '
               'Use /support for private account or billing help.')


def ensure_review_thread(http, store, *, guild, owner):
    channels = request(http, 'GET', f'/guilds/{guild}/channels', 'READ_REVIEW_PARENT')
    lounge = next(c for c in channels if c['type'] == 0 and channel_name(c['name']) == 'vip-lounge')
    roles = request(http, 'GET', f'/guilds/{guild}/roles', 'READ_REVIEW_ROLES')
    bot = str(request(http, 'GET', '/users/@me', 'READ_REVIEW_BOT')['id'])
    info = request(http, 'GET', f'/guilds/{guild}', 'READ_REVIEW_OWNER')
    if str(info['owner_id']) != str(owner):
        raise ValueError('Review owner mismatch')
    approved = set(vip_role_ids(roles)) | {str(r['id']) for r in roles if r['name'].upper() in STAFF_NAMES or int(r.get('permissions', 0)) & 8}
    if effective_permissions(guild, '0', [], roles, lounge, owner) & VIEW:
        raise ValueError('Review parent is public')
    for overwrite in lounge.get('permission_overwrites', []):
        if int(overwrite['allow']) & VIEW and str(overwrite['id']) not in approved | {str(owner), bot}:
            raise ValueError('Review parent has unapproved access')
    saved = store.list_records('discord_intro_receipt', 1, entity=str(lounge['id']))
    if not saved:
        raise ValueError('Verified lounge introduction required')
    mid = saved[0]['payload']['message_id']
    response = http.get(f'/channels/{mid}')
    if response.status_code == 404:
        claim = digest(['discord_review_thread', guild, mid])
        if not store.append('discord_review_thread_claim', mid, {'status': 'CLAIMED'}, claim):
            raise RuntimeError('Review thread delivery requires inspection')
        thread = request(http, 'POST', f'/channels/{lounge["id"]}/messages/{mid}/threads', 'CREATE_MEMBER_REVIEW_THREAD',
                         json={'name': REVIEW_NAME, 'auto_archive_duration': 1440})
    elif response.status_code == 200:
        thread = response.json()
    else:
        raise RuntimeError('Review thread lookup failed')
    tid = str(thread['id'])
    if tid != str(mid) or str(thread['parent_id']) != str(lounge['id']) or str(thread['guild_id']) != str(guild) or thread['type'] != 11:
        raise ValueError('Review thread identity mismatch')
    # Keep the shared entry point usable; never replace it after auto-archive.
    if thread.get('thread_metadata', {}).get('archived'):
        request(http, 'PATCH', f'/channels/{tid}', 'REOPEN_MEMBER_REVIEW_THREAD', json={'archived': False})
    receipts = store.list_records('discord_review_template_receipt', 1, entity=tid)
    if receipts:
        template_id = receipts[0]['payload']['message_id']
    else:
        claim = digest(['discord_review_template', tid])
        if not store.append('discord_review_template_claim', tid, {}, claim):
            raise RuntimeError('Review template delivery requires inspection')
        row = request(http, 'POST', f'/channels/{tid}/messages', 'POST_MEMBER_REVIEW_TEMPLATE',
                      json={'content': REVIEW_TEXT, 'allowed_mentions': {'parse': []}, 'nonce': claim[:24], 'enforce_nonce': True})
        template_id = str(row['id'])
        store.append('discord_review_template_receipt', tid, {'message_id': template_id}, digest(['review_receipt', tid]))
    verified = request(http, 'GET', f'/channels/{tid}/messages/{template_id}', 'VERIFY_MEMBER_REVIEW_TEMPLATE')
    if verified.get('content') != REVIEW_TEXT or str(verified.get('author', {}).get('id')) != bot:
        raise RuntimeError('Review template verification failed')
    verified_thread = request(http, 'GET', f'/channels/{tid}', 'VERIFY_MEMBER_REVIEW_THREAD')
    if verified_thread.get('thread_metadata', {}).get('archived') or verified_thread.get('name') != REVIEW_NAME:
        raise RuntimeError('Review thread verification failed')
    return {'status': 'VERIFIED', 'thread_id': tid, 'template_id': template_id}


def preview_payload(record, *, now):
    if not record:
        return None
    p = record['payload']
    stamp = datetime.fromisoformat(p['completed_at'])
    if stamp.tzinfo is None or not 0 <= (now - stamp).total_seconds() <= 10800 or not p.get('healthy') or p.get('truncated') or p.get('error_count'):
        return None
    rows = p.get('rows', [])
    if not rows:
        return None
    # Only aggregate metadata leaves the premium feed. No selections, raw API
    # reasons, private links, member information, odds or stakes are copied.
    games = len({(r.get('sport'), r.get('event_id') or r.get('event')) for r in rows})
    ct = stamp.astimezone(ZoneInfo('America/Chicago'))
    return {'title': 'PUBLIC RESEARCH PREVIEW • NOT A PICK', 'color': 0x8B35E8,
            'description': f'**Inside one recent research scan**\n{games} matchups represented • {len(rows)} research rows\n'
                           f'Snapshot: {ct:%b %d, %I:%M %p} CT\n\n'
                           '**How we screen:** data health → current market price → model uncertainty → reliability and exposure checks. '
                           'A healthy scan does not mean the model is approved for cash bets.\n\n'
                           'WATCH and PASS are valid outcomes. Research leans are not official wagers. '
                           'This snapshot covers returned research only, not a verified complete league schedule.',
            'footer': {'text': 'JABBAZI GURU · Research process preview'}}


async def publish_public_preview(client, store, config, *, now=None):
    import discord
    now = now or datetime.now(UTC)
    week = now.astimezone(ZoneInfo('America/Chicago')).strftime('%G-W%V')
    key = digest(['discord_public_preview', config.guild, week])
    if store.list_records('discord_public_preview_claim', 1, entity=key):
        return 'DUPLICATE'
    record = await asyncio.to_thread(latest_sheet, store, now=now)
    payload = preview_payload(record, now=now)
    if payload is None:
        return 'NO_HEALTHY_SNAPSHOT'
    channel = await client.checked_public_channel(config.general_channel)
    if not await asyncio.to_thread(store.append, 'discord_public_preview_claim', key, {'source_id': record['id']}, key):
        return 'DUPLICATE'
    sent = await channel.send(embed=discord.Embed.from_dict(payload), allowed_mentions=discord.AllowedMentions.none(), nonce=key[:24])
    verified = await channel.fetch_message(sent.id)
    if len(verified.embeds) != 1 or any(verified.embeds[0].to_dict().get(k) != v for k, v in payload.items()):
        raise RuntimeError('Public preview readback failed')
    await asyncio.to_thread(store.append, 'discord_public_preview_receipt', key,
                            {'channel_id': str(channel.id), 'message_id': str(sent.id)}, digest(['preview_receipt', key]))
    print(f'DISCORD_PUBLIC_PREVIEW_VERIFIED CHANNEL={channel.id} MESSAGE={sent.id} WEEK={week}', flush=True)
    return 'DELIVERED'

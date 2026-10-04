"""Owner-approved, one-time membership banner announcement; never replay a ping."""
import hashlib
import json
from pathlib import Path

from .discord_migration import VIEW, SEND, READ, effective_permissions, request
from .persistence.store import digest

GUILD = '1552043745153650840'
CHANNEL = '1554590523921272943'
CAMPAIGN = 'vip-banner-owner-approved-2026-09-29'
FILENAME = 'jabbazi-vip-banner.png'
TEXT = ('@everyone\n💎 **WELCOME TO JABBAZI GURU VIP**\n\n'
        'Explore the official Main Card, daily moneyline sheet, VIP research and our private lounge.\n'
        'See the pinned membership guide here for access details. '
        'For current plans or private help, use **/support** in <#1552129273517711421>.')


def announce(http, store, *, guild, owner):
    if str(guild) != GUILD:
        return {'status': 'NOT_TARGET_GUILD'}
    key = digest([CAMPAIGN, GUILD, CHANNEL])
    receipts = store.list_records('discord_banner_receipt', 1, entity=key)
    if receipts:
        mid = receipts[0]['payload']['message_id']
        row = request(http, 'GET', f'/channels/{CHANNEL}/messages/{mid}', 'VERIFY_EXISTING_MEMBERSHIP_BANNER')
        verify(row)
        return {'status': 'VERIFIED_ALREADY_POSTED', 'channel_id': CHANNEL, 'message_id': mid, 'mention_everyone': True}
    info = request(http, 'GET', f'/guilds/{guild}', 'READ_ANNOUNCEMENT_OWNER')
    if str(info['owner_id']) != str(owner):
        raise ValueError('Announcement owner mismatch')
    bot = str(request(http, 'GET', '/users/@me', 'READ_ANNOUNCEMENT_BOT')['id'])
    channel = request(http, 'GET', f'/channels/{CHANNEL}', 'READ_ANNOUNCEMENT_CHANNEL')
    if str(channel['guild_id']) != GUILD or channel['type'] != 0:
        raise ValueError('Announcement channel mismatch')
    roles = request(http, 'GET', f'/guilds/{guild}/roles', 'READ_ANNOUNCEMENT_ROLES')
    member = request(http, 'GET', f'/guilds/{guild}/members/{bot}', 'READ_ANNOUNCEMENT_MEMBERSHIP')
    permissions = effective_permissions(guild, bot, member['roles'], roles, channel, owner)
    if not effective_permissions(guild, 'free-simulation', [], roles, channel, owner) & VIEW:
        raise ValueError('Membership announcement must be public')
    required = VIEW | SEND | READ | (1 << 15) | (1 << 17)
    if permissions & required != required:
        return {'status': 'PERMISSION_REQUIRED', 'missing_bits': str(required & ~permissions), 'channel_id': CHANNEL}
    image = Path('docs/discord/assets/' + FILENAME).read_bytes()
    if not image.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Banner must be the approved PNG')
    payload = {'content': TEXT, 'allowed_mentions': {'parse': ['everyone'], 'users': [], 'roles': [], 'replied_user': False},
               'attachments': [{'id': 0, 'filename': FILENAME, 'description': 'JABBAZI GURU VIP Membership — black and purple stadium banner'}],
               'nonce': key[:24], 'enforce_nonce': True}
    if not store.append('discord_banner_claim', key, {'status': 'CLAIMED', 'image_sha256': hashlib.sha256(image).hexdigest()}, key):
        return {'status': 'DELIVERY_REQUIRES_REVIEW', 'channel_id': CHANNEL}
    # Deliberately no automatic POST retry after uncertain delivery.
    response = http.post(f'/channels/{CHANNEL}/messages', data={'payload_json': json.dumps(payload)}, files={'files[0]': (FILENAME, image, 'image/png')})
    if response.status_code not in (200, 201):
        raise RuntimeError('Banner upload failed HTTP_' + str(response.status_code))
    mid = str(response.json()['id'])
    store.append('discord_banner_receipt', key, {'message_id': mid}, digest(['banner_receipt', key]))
    row = request(http, 'GET', f'/channels/{CHANNEL}/messages/{mid}', 'VERIFY_MEMBERSHIP_BANNER')
    verify(row)
    return {'status': 'POSTED_VERIFIED', 'channel_id': CHANNEL, 'message_id': mid, 'mention_everyone': True}


def verify(row):
    if row.get('content') != TEXT or not row.get('mention_everyone'):
        raise RuntimeError('Banner announcement or everyone mention not verified')
    if not any(a.get('filename') == FILENAME and a.get('size', 0) > 0 and a.get('width', 0) > 0 for a in row.get('attachments', [])):
        raise RuntimeError('Banner attachment not verified')

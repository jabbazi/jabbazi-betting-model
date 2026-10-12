"""Owner-approved membership announcement with hot-pink JABBAZI banner.

Existing announcement is updated in place with mentions disabled, so rebranding
never emits a second @everyone ping.
"""
import hashlib
import io
import json

from PIL import Image, ImageDraw, ImageFont

from .discord_migration import VIEW, SEND, READ, effective_permissions, request
from .persistence.store import digest

GUILD = '1552043745153650840'
CHANNEL = '1554590523921272943'
CAMPAIGN = 'vip-banner-owner-approved-2026-09-29'
FILENAME = 'jabbazi-vip-banner.png'
TEXT = ('@everyone\n💎 **WELCOME TO JABBAZI VIP**\n\n'
        'Explore the official Main Card, daily game cheat sheets, VIP research and our private lounge.\n'
        'See the pinned membership guide here for access details. '
        'For current plans or private help, use **/support** in <#1552129273517711421>.')

HOT_PINK = (255, 10, 138)
NEON_PINK = (255, 20, 147)
BLACK = (9, 9, 9)
GRAPHITE = (26, 26, 31)
WHITE = (255, 255, 255)
SILVER = (217, 217, 217)
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def banner_bytes():
    image = Image.new("RGB", (1200, 420), BLACK)
    draw = ImageDraw.Draw(image)
    for x in range(-200, 1400, 100):
        draw.line((x, 420, x + 360, 0), fill=(35, 8, 24), width=4)
    draw.rectangle((14, 14, 1186, 406), outline=HOT_PINK, width=4)
    draw.line((70, 320, 1130, 320), fill=NEON_PINK, width=4)
    title = ImageFont.truetype(FONT_BOLD, 118)
    sub = ImageFont.truetype(FONT_BOLD, 54)
    small = ImageFont.truetype(FONT_REG, 25)
    box = draw.textbbox((0, 0), "JABBAZI", font=title)
    x = (1200 - (box[2] - box[0])) // 2
    draw.text((x + 6, 74), "JABBAZI", font=title, fill=(180, 0, 82))
    draw.text((x, 68), "JABBAZI", font=title, fill=WHITE)
    box = draw.textbbox((0, 0), "INNER CIRCLE", font=sub)
    x = (1200 - (box[2] - box[0])) // 2
    draw.text((x, 205), "INNER CIRCLE", font=sub, fill=HOT_PINK)
    footer = "MAIN CARD  •  RESEARCH  •  COMMUNITY  •  PERFORMANCE"
    box = draw.textbbox((0, 0), footer, font=small)
    draw.text(((1200 - (box[2] - box[0])) // 2, 347), footer, font=small, fill=SILVER)
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def _edit_existing(http, mid, image):
    payload = {
        'content': TEXT,
        'allowed_mentions': {'parse': []},
        'attachments': [{
            'id': 0,
            'filename': FILENAME,
            'description': 'JABBAZI VIP Membership — black and hot-pink JABBAZI banner',
        }],
    }
    response = http.patch(
        f'/channels/{CHANNEL}/messages/{mid}',
        data={'payload_json': json.dumps(payload)},
        files={'files[0]': (FILENAME, image, 'image/png')},
    )
    if response.status_code not in (200, 201):
        raise RuntimeError('Membership banner rebrand failed HTTP_' + str(response.status_code))
    return response.json()


def announce(http, store, *, guild, owner):
    if str(guild) != GUILD:
        return {'status': 'NOT_TARGET_GUILD'}
    key = digest([CAMPAIGN, GUILD, CHANNEL])
    image = banner_bytes()
    receipts = store.list_records('discord_banner_receipt', 1, entity=key)
    if receipts:
        mid = receipts[0]['payload']['message_id']
        row = request(http, 'GET', f'/channels/{CHANNEL}/messages/{mid}', 'VERIFY_EXISTING_MEMBERSHIP_BANNER')
        attachment = next((a for a in row.get('attachments', []) if a.get('filename') == FILENAME), None)
        needs_visual_refresh = (
            row.get('content') != TEXT
            or attachment is None
            or int(attachment.get('size') or 0) != len(image)
            or 'hot-pink' not in str(attachment.get('description') or '').lower()
        )
        if needs_visual_refresh:
            row = _edit_existing(http, mid, image)
        verify(row, require_everyone=False, expected_size=len(image))
        return {
            'status': 'VERIFIED_HOT_PINK',
            'channel_id': CHANNEL,
            'message_id': mid,
            'mention_everyone': bool(row.get('mention_everyone')),
            'image_sha256': hashlib.sha256(image).hexdigest(),
        }

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
    payload = {
        'content': TEXT,
        'allowed_mentions': {'parse': ['everyone'], 'users': [], 'roles': [], 'replied_user': False},
        'attachments': [{
            'id': 0,
            'filename': FILENAME,
            'description': 'JABBAZI VIP Membership — black and hot-pink JABBAZI banner',
        }],
        'nonce': key[:24],
        'enforce_nonce': True,
    }
    if not store.append('discord_banner_claim', key, {'status': 'CLAIMED', 'image_sha256': hashlib.sha256(image).hexdigest()}, key):
        return {'status': 'DELIVERY_REQUIRES_REVIEW', 'channel_id': CHANNEL}
    response = http.post(
        f'/channels/{CHANNEL}/messages',
        data={'payload_json': json.dumps(payload)},
        files={'files[0]': (FILENAME, image, 'image/png')},
    )
    if response.status_code not in (200, 201):
        raise RuntimeError('Banner upload failed HTTP_' + str(response.status_code))
    mid = str(response.json()['id'])
    store.append('discord_banner_receipt', key, {'message_id': mid}, digest(['banner_receipt', key]))
    row = request(http, 'GET', f'/channels/{CHANNEL}/messages/{mid}', 'VERIFY_MEMBERSHIP_BANNER')
    verify(row, expected_size=len(image))
    return {'status': 'POSTED_VERIFIED', 'channel_id': CHANNEL, 'message_id': mid, 'mention_everyone': True}


def verify(row, require_everyone=True, expected_size=None):
    if row.get('content') != TEXT or (require_everyone and not row.get('mention_everyone')):
        raise RuntimeError('Banner announcement content or mention state not verified')
    attachment = next(
        (a for a in row.get('attachments', []) if a.get('filename') == FILENAME and a.get('width', 0) > 0),
        None,
    )
    if attachment is None:
        raise RuntimeError('Banner attachment not verified')
    if expected_size is not None and int(attachment.get('size') or 0) != int(expected_size):
        raise RuntimeError('Banner attachment size mismatch')

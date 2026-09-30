"""Member-intent preflight and one welcome per genuine join, never a startup sweep."""
from __future__ import annotations

import asyncio

import httpx

from .discord_migration import POSTING, READ, VIEW, request
from .persistence.store import digest

MEMBERS = 1 << 14
MEMBERS_LIMITED = 1 << 15


def enable_member_intent(token, store):
    try:
        with httpx.Client(base_url='https://discord.com/api/v10', headers={'Authorization': 'Bot ' + token}, timeout=20) as http:
            app = request(http, 'GET', '/oauth2/applications/@me', 'READ_MEMBER_INTENT')
            flags = int(app.get('flags', 0))
            if not flags & (MEMBERS | MEMBERS_LIMITED):
                snapshot = {'application_id': str(app['id']), 'flags': flags}
                key = digest(['discord_intent_backup', snapshot])
                store.append('discord_intent_backup', str(app['id']), snapshot, key)
                if not any(r['id'] == key for r in store.list_records('discord_intent_backup', 100, entity=str(app['id']))):
                    raise RuntimeError('Intent backup verification failed')
                request(http, 'PATCH', '/applications/@me', 'ENABLE_SERVER_MEMBERS_INTENT', json={'flags': flags | MEMBERS_LIMITED})
                app = request(http, 'GET', '/oauth2/applications/@me', 'VERIFY_MEMBER_INTENT')
            enabled = bool(int(app.get('flags', 0)) & (MEMBERS | MEMBERS_LIMITED))
            print('DISCORD_SERVER_MEMBERS_INTENT_' + ('VERIFIED' if enabled else 'UNAVAILABLE'), flush=True)
            return enabled
    except Exception as exc:
        print(f'DISCORD_SERVER_MEMBERS_INTENT_UNAVAILABLE_{type(exc).__name__}', flush=True)
        return False  # Optional welcome setup must not take commands/publishing offline.


async def welcome_member(client, store, config, member):
    import discord

    if member.bot or member.guild.id != config.guild or not config.members_enabled:
        return 'SKIPPED'
    joined = member.joined_at
    if joined is None or joined.tzinfo is None:
        return 'MISSING_JOIN_TIMESTAMP'
    ids = [config.welcome_channel, config.guide_channel, config.access_channel, config.general_channel]
    if not all(ids) or len(set(ids)) != 4:
        raise ValueError('Welcome navigation is not configured')
    channels = [await client.checked_public_channel(cid) for cid in ids]
    channel = channels[0]
    permissions = channel.permissions_for(channel.guild.default_role).value
    if permissions & (VIEW | READ) != VIEW | READ or permissions & POSTING:
        raise ValueError('Welcome must be publicly readable and read-only')
    key = digest(['discord_member_join', config.guild, member.id, joined.isoformat()])
    claimed = await asyncio.to_thread(store.append, 'discord_member_join', key,
                                      {'guild_id': str(config.guild), 'member_id': str(member.id), 'joined_at': joined.isoformat(), 'status': 'CLAIMED'}, key)
    if not claimed:
        return 'DUPLICATE'
    message = (f'👋 **Welcome to JABBAZI GURU, <@{member.id}>!**\n\n'
               f'Start with <#{config.guide_channel}>, visit <#{config.access_channel}> for VIP information, '
               f'and introduce yourself in <#{config.general_channel}>.\n\n'
               'Choose your notifications with **/alerts**.\nNeed help? Use **/support**.\n\nGlad to have you here! 🟣')
    # The durable claim deliberately prevents replay after an ambiguous send.
    # A genuine rejoin has a new joined_at and therefore a new claim.
    sent = await channel.send(message, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[discord.Object(id=member.id)], replied_user=False), nonce=key[:24])
    verified = await channel.fetch_message(sent.id)
    if verified.content != message:
        raise RuntimeError('Welcome content verification failed')
    await asyncio.to_thread(store.append, 'discord_welcome_receipt', key,
                            {'channel_id': str(channel.id), 'message_id': str(sent.id), 'status': 'DELIVERED'}, digest(['discord_welcome_receipt', key]))
    print(f'DISCORD_MEMBER_WELCOME_DELIVERED CHANNEL={channel.id} MESSAGE={sent.id}', flush=True)
    return 'DELIVERED'

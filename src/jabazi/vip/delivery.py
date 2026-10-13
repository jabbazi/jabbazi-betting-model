"""Opt-in private watchlist notifications; no unsolicited DMs or stale replay."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select

from ..persistence.store import events, digest
from ..daily_scope import delivery_eligible
from .data import board, age_ok
from .state import read_state


def quiet(prefs, now):
    start, end = prefs.get('quiet_start'), prefs.get('quiet_end')
    if start is None or end is None:
        return False
    hour = now.astimezone(ZoneInfo('America/Chicago')).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def enabled(prefs, notification, now):
    category = 'price' if 'PRICE' in notification.get('state', '') else 'status'
    return (prefs.get('discord_dm') is True and prefs.get('notifications', True)
            and category in prefs.get('alert_categories', ['price', 'status'])
            and (not prefs.get('sports') or notification.get('sport') in prefs['sports'])
            and not quiet(prefs, now))


async def deliver_watch_dms(client, store, config, *, now=None):
    import asyncio
    import discord
    from ..discord_bot import member_has_vip
    now = now or datetime.now(UTC)
    # Work is bounded per poll; pagination/backlogs are not replayed as fresh alerts.
    def load():
        with store.engine.connect() as conn:
            return list(conn.execute(select(events).where(events.c.kind == 'vip_notification').order_by(events.c.occurred_at.desc()).limit(50)).mappings())
    records = await asyncio.to_thread(load)
    if not records:
        return
    current = None
    for record in records:
        owner, notification = record['entity'], record['payload']
        parts = owner.split(':')
        if len(parts) != 2 or parts[0] != str(config.guild) or not parts[1].isdigit():
            continue
        if not age_ok(notification.get('at'), now, 300):
            continue
        prefs = await asyncio.to_thread(read_state, store, 'vip_preferences', owner)
        key = digest(['watch_dm', record['id']])
        if prefs.get('discord_dm') is True and quiet(prefs, now):
            await asyncio.to_thread(store.append, 'vip_dm_claim', key, {'state':'SUPPRESSED_QUIET_HOURS'}, key)
            continue
        if not enabled(prefs, notification, now):
            continue
        watches = await asyncio.to_thread(read_state, store, 'vip_watchlist', owner)
        watch = next((w for w in watches.get('items', []) if w['id'] == notification['id']), None)
        if watch is None:
            continue
        key = digest(['watch_dm', record['id']])
        attempts = await asyncio.to_thread(store.list_records, 'vip_dm_receipt', 3, entity=key)
        if len(attempts) >= 3:
            continue
        if await asyncio.to_thread(store.list_records, 'vip_dm_claim', 1, entity=key):
            continue
        if current is None:
            current = await asyncio.to_thread(board, store)
        row = next((r for r in current['rows'] if r['id'] == notification['id']), None)
        if not row or not row['fresh'] or row.get('data_health') != 'HEALTHY' or row.get('status') in {'QUARANTINED', 'INVALIDATED', 'PASS'} or row.get('decimal') != notification.get('price'):
            continue
        if notification.get('state') == 'PRICE TARGET MET' and watch.get('threshold') and row['decimal'] < watch['threshold']:
            continue
        guild = client.get_guild(config.guild)
        if guild is None:
            continue
        try:
            member = await guild.fetch_member(int(parts[1]))
            if not member_has_vip(config, member):
                continue
            # Final entitlement, schedule and preference checks occur before claim/send.
            prefs = await asyncio.to_thread(read_state, store, 'vip_preferences', owner)
            if not enabled(prefs, notification, datetime.now(UTC)):
                continue
            from ..models.team_elo import SPORTS
            scope = {**row, 'sport': SPORTS.get(row['sport'].lower(), row['sport'])}
            if not age_ok(row.get('price_at'), datetime.now(UTC), 300) or not await asyncio.to_thread(delivery_eligible, store, [scope]):
                continue
            if not await asyncio.to_thread(store.append, 'vip_dm_claim', key, {'at': now.isoformat()}, key):
                continue
            text = ('JABBAZI • PRIVATE WATCHLIST\n'+row['event']+'\n'+str(row['selection'])+' · '+str(row.get('line') or '')+
                    '\n'+notification['state']+' · observed decimal price '+str(row['decimal'])+
                    '\nPrice observed: '+str(row['price_at'])+'\nResearch only, not an official wager. Manage or disable DMs in VIP Settings.')
            message = await member.send(text, allowed_mentions=discord.AllowedMentions.none(), nonce=int(key[:15],16))
            await asyncio.to_thread(store.append, 'vip_dm_receipt', key, {'state':'SENT', 'message_id':str(message.id), 'at':datetime.now(UTC).isoformat()})
        except Exception as exc:
            # Ambiguous network sends are not retried: avoids duplicate member messages.
            await asyncio.to_thread(store.append, 'vip_dm_receipt', key, {'state':'FAILED_OR_UNKNOWN', 'error_type':type(exc).__name__, 'at':datetime.now(UTC).isoformat()})

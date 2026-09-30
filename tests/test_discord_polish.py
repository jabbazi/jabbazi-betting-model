import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest

from jabazi.discord_bot import BotConfig, validate_target
from jabazi.discord_migration import APP_COMMANDS, POSTING, READ, VIEW, effective_permissions, overwrites
from jabazi.discord_onboarding import seed
from jabazi.discord_welcome import MEMBERS_LIMITED, enable_member_intent, welcome_member
from jabazi.persistence.store import Store


@pytest.fixture
def store(tmp_path):
    db = Store('sqlite:///' + str(tmp_path / 'polish.db'), initialize=True)
    yield db
    db.close()


def test_read_only_blocks_posting_and_both_thread_types_for_all_vip_roles():
    roles = [{'id': '1', 'permissions': str(VIEW | READ | POSTING | APP_COMMANDS)}] + [{'id': str(i), 'permissions': str(POSTING)} for i in range(7, 12)]
    for access in ('public', 'vip', 'staff'):
        channel = {'permission_overwrites': overwrites(access, guild='1', owner='2', bot='9', vip={'7', '8', '10', '11'}, staff={'12'}, read_only=True)}
        for assigned in ([], ['7'], ['8'], ['10'], ['11'], ['7', '8', '10', '11'], ['12']):
            actual = effective_permissions('1', 'test', assigned, roles, channel, '2')
            assert not actual & POSTING
        assert effective_permissions('1', '9', [], roles, channel, '2') & (VIEW | READ | (1 << 11)) == VIEW | READ | (1 << 11)
        assert effective_permissions('1', '2', [], roles, channel, '2') & POSTING == POSTING


def test_research_and_market_channels_are_approved_but_still_private():
    config = BotConfig(1, 2, 3, 4, frozenset(), research_channel=5, market_channel=6)
    for cid in (5, 6):
        doc = {'guild_id': '1', 'id': str(cid), 'type': 0, 'permission_overwrites': [{'id': '1', 'type': 0, 'allow': '0', 'deny': str(VIEW)}]}
        validate_target(doc, config, 9)
        doc['permission_overwrites'][0]['deny'] = '0'
        with pytest.raises(ValueError):
            validate_target(doc, config, 9)


@pytest.mark.parametrize('blocked', [False, True])
def test_intent_enable_is_backed_up_and_verified_or_fails_soft(store, monkeypatch, blocked):
    flags = 1 << 18
    calls = []
    def handler(req):
        nonlocal flags
        calls.append(req.method)
        if req.method == 'PATCH':
            assert store.list_records('discord_intent_backup', 1)
            assert req.url.path.endswith('/applications/@me')
            if blocked:
                return httpx.Response(403, json={'code': 50013, 'message': 'private'})
            flags = json.loads(req.content)['flags']
        return httpx.Response(200, json={'id': '9', 'flags': flags})
    real = httpx.Client
    monkeypatch.setattr('jabazi.discord_welcome.httpx.Client', lambda **kw: real(**kw, transport=httpx.MockTransport(handler)))
    assert enable_member_intent('secret', store) is (not blocked)
    assert bool(flags & MEMBERS_LIMITED) is (not blocked)
    if not blocked:
        assert enable_member_intent('secret', store)
        assert calls.count('PATCH') == 1
        assert flags & (1 << 18)


def test_welcome_exactly_once_across_restart_rejoin_allowed_bots_skipped(store):
    async def run():
        config = BotConfig(1, 2, 3, 4, frozenset(), welcome_channel=5, guide_channel=6, access_channel=7, general_channel=8, members_enabled=True)
        messages = {}
        async def send(content, **kwargs):
            mentions = kwargs['allowed_mentions'].to_dict()
            assert mentions.get('users') == [42]
            assert not mentions['parse']
            assert '<@42>' in content and all(f'<#{n}>' in content for n in (6, 7, 8))
            assert 'access=' not in content
            mid = len(messages) + 100
            messages[mid] = NS(id=mid, content=content)
            return messages[mid]
        channel = NS(id=5, guild=NS(default_role=object()), permissions_for=lambda _: NS(value=VIEW | READ), send=AsyncMock(side_effect=send), fetch_message=AsyncMock(side_effect=lambda mid: messages[mid]))
        client = NS(checked_public_channel=AsyncMock(return_value=channel))
        member = NS(id=42, bot=False, guild=NS(id=1), joined_at=datetime.now(UTC))
        assert await welcome_member(client, store, config, member) == 'DELIVERED'
        # New client instance shares the persistent receipt after a reconnect/restart.
        client = NS(checked_public_channel=AsyncMock(return_value=channel))
        assert await welcome_member(client, store, config, member) == 'DUPLICATE'
        member.joined_at += timedelta(hours=1)
        assert await welcome_member(client, store, config, member) == 'DELIVERED'
        member.bot = True
        assert await welcome_member(client, store, config, member) == 'SKIPPED'
        assert channel.send.await_count == 2
        assert len(store.list_records('discord_welcome_receipt')) == 2
        member.bot = False
        assert await welcome_member(client, store, replace(config, members_enabled=False), member) == 'SKIPPED'
    asyncio.run(run())


def test_ambiguous_welcome_send_does_not_replay(store):
    async def run():
        config = BotConfig(1, 2, 3, 4, frozenset(), welcome_channel=5, guide_channel=6, access_channel=7, general_channel=8, members_enabled=True)
        channel = NS(guild=NS(default_role=object()), permissions_for=lambda _: NS(value=VIEW | READ), send=AsyncMock(side_effect=TimeoutError))
        client = NS(checked_public_channel=AsyncMock(return_value=channel))
        member = NS(id=42, bot=False, guild=NS(id=1), joined_at=datetime.now(UTC))
        with pytest.raises(TimeoutError):
            await welcome_member(client, store, config, member)
        assert await welcome_member(client, store, config, member) == 'DUPLICATE'
        channel.send.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize('pin_blocked', [False, True])
def test_intro_backup_idempotency_pin_reuse_and_unpin_preserves_history(store, pin_blocked):
    from pathlib import Path
    bp = json.loads(Path('docs/discord/server_blueprint.json').read_text())
    channels = []
    for n, cat in enumerate(bp['categories'], 100):
        channels.append({'id': str(n), 'type': 4, 'name': cat['name']})
        for name in cat['channels']:
            channels.append({'id': str(1000 + len(channels)), 'type': 0, 'parent_id': str(n), 'name': bp['channel_display_names'][name]})
    messages = {c['id']: {} for c in channels if c['type'] == 0}
    welcome = next(c['id'] for c in channels if c['name'].endswith('│welcome'))
    messages[welcome]['10'] = {'id': '10', 'author': {'id': '9'}, 'content': 'Old guide JABBAZI_SETUP_V3', 'pinned': True}
    messages[welcome]['11'] = {'id': '11', 'author': {'id': '9'}, 'content': 'Duplicate guide JABBAZI_SETUP_V2', 'pinned': True}
    messages[welcome]['12'] = {'id': '12', 'author': {'id': '2'}, 'content': 'Important historical message', 'pinned': True}
    posts = []
    def handler(req):
        path = req.url.path.removeprefix('/api/v10')
        if path == '/guilds/1': value = {'owner_id': '2'}
        elif path == '/users/@me': value = {'id': '9'}
        elif path == '/guilds/1/channels': value = channels
        else:
            parts = path.split('/')
            cid = parts[2]
            if req.method != 'GET':
                assert store.list_records('discord_intro_backup', 1, entity=cid)
            if parts[-1] == 'pins':
                value = {'items': [{'message': m, 'pinned_at': '2026-09-30T00:00:00Z'} for m in messages[cid].values() if m['pinned']], 'has_more': False}
            elif 'pins' in parts:
                if pin_blocked:
                    return httpx.Response(403, json={'code': 50013})
                messages[cid][parts[-1]]['pinned'] = req.method == 'PUT'
                return httpx.Response(204)
            elif parts[-1] == 'messages':
                if req.method == 'POST':
                    mid = str(10000 + len(posts))
                    value = {'id': mid, 'author': {'id': '9'}, 'pinned': False, **json.loads(req.content)}
                    messages[cid][mid] = value
                    posts.append(mid)
                else:
                    value = list(messages[cid].values())
            else:
                value = messages[cid][parts[-1]]
                if req.method == 'PATCH': value.update(json.loads(req.content))
        return httpx.Response(200, json=value)
    with httpx.Client(base_url='https://discord.com/api/v10', transport=httpx.MockTransport(handler)) as http:
        first = seed(http, store, guild='1', owner='2', apply=True)
        second = seed(http, store, guild='1', owner='2', apply=True)
    assert len(posts) == 17  # Reuses the existing welcome and creates only missing guides.
    assert [p['message_id'] for p in first['plan']] == [p['message_id'] for p in second['plan']]
    assert all(p['status'] == ('INTRO_VERIFIED_PIN_UNAVAILABLE' if pin_blocked else 'PINNED') for p in second['plan'])
    assert messages[welcome]['12']['pinned']
    assert messages[welcome]['11']['pinned'] is pin_blocked
    assert 'Old guide' not in messages[welcome]['10']['content']
    assert store.list_records('discord_intro_backup', 100, entity=welcome)

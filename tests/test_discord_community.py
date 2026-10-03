import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest

from jabazi.discord_community import REVIEW_NAME, REVIEW_TEXT, ensure_review_thread, preview_payload, publish_public_preview
from jabazi.discord_migration import VIEW, overwrites
from jabazi.discord_onboarding import guide_payload, matches_guide, is_introduction
from jabazi.persistence.store import Store


@pytest.fixture
def store(tmp_path):
    db = Store('sqlite:///' + str(tmp_path / 'community.db'), initialize=True)
    yield db
    db.close()


def test_embed_identity_and_discord_added_metadata():
    payload = guide_payload('💎 **VIP**\nUseful text\n\n*JABBAZI GURU · Channel guide*')
    row = {**payload, 'embeds': [{**payload['embeds'][0], 'type': 'rich'}]}
    assert matches_guide(row, payload) and is_introduction(row)
    assert payload['embeds'][0]['color'] == 0x8B35E8
    assert payload['embeds'][0]['description'] == 'Useful text'
    assert not matches_guide({**row, 'content': 'competing text'}, payload)


@pytest.mark.parametrize('public', [False, True])
def test_review_thread_singleton_restart_and_parent_privacy(store, public):
    store.append('discord_intro_receipt', '10', {'message_id': '20'}, 'intro')
    lounge = {'id': '10', 'type': 0, 'name': '💎│vip-lounge', 'permission_overwrites': overwrites('public' if public else 'vip', guild='1', owner='2', bot='9', vip={'7'}, staff=set())}
    threads, posts = {}, []
    def handler(req):
        path = req.url.path
        if path == '/guilds/1': value = {'owner_id': '2'}
        elif path == '/users/@me': value = {'id': '9'}
        elif path == '/guilds/1/channels': value = [lounge]
        elif path == '/guilds/1/roles': value = [{'id': '1', 'name': '@everyone', 'permissions': str(VIEW)}, {'id': '7', 'name': 'VIP', 'permissions': '0'}]
        elif path == '/channels/10/messages/20/threads':
            assert req.method == 'POST'
            assert not threads
            threads['20'] = value = {'id': '20', 'guild_id': '1', 'parent_id': '10', 'type': 11, 'name': REVIEW_NAME, 'thread_metadata': {'archived': False}}
        elif path == '/channels/20':
            if not threads: return httpx.Response(404)
            value = threads['20']
            if req.method == 'PATCH': value['thread_metadata']['archived'] = False
        elif path == '/channels/20/messages':
            posts.append(json.loads(req.content))
            value = {'id': '30'}
        elif path == '/channels/20/messages/30': value = {'id': '30', 'author': {'id': '9'}, 'content': REVIEW_TEXT}
        else: raise AssertionError(path)
        return httpx.Response(200, json=value)
    with httpx.Client(base_url='https://discord.test', transport=httpx.MockTransport(handler)) as http:
        if public:
            with pytest.raises(ValueError, match='public'):
                ensure_review_thread(http, store, guild='1', owner='2')
            assert not posts and not threads
        else:
            first = ensure_review_thread(http, store, guild='1', owner='2')
            threads['20']['thread_metadata']['archived'] = True
            assert ensure_review_thread(http, store, guild='1', owner='2') == first
            assert len(posts) == 1 and posts[0]['allowed_mentions'] == {'parse': []}


def sample(now):
    return {'id': 'research', 'payload': {'healthy': True, 'completed_at': now.isoformat(), 'error_count': 0, 'truncated': False,
            'rows': [{'sport': 'NFL', 'event_id': 'event', 'selection': 'SECRET PICK', 'reason': 'PRIVATE LINK'}, {'sport': 'NFL', 'event_id': 'event'}]}}


@pytest.mark.parametrize('change', [{'healthy': False}, {'error_count': 1}, {'truncated': True}, {'rows': []}])
def test_preview_rejects_incomplete_data(change):
    now = datetime.now(UTC)
    record = sample(now)
    record['payload'].update(change)
    assert preview_payload(record, now=now) is None


def test_preview_freshness_and_no_premium_contents():
    now = datetime.now(UTC)
    record = sample(now)
    payload = preview_payload(record, now=now)
    assert '1 matchups represented' in payload['description']
    assert 'SECRET' not in json.dumps(payload) and 'PRIVATE' not in json.dumps(payload)
    assert preview_payload(record, now=now + timedelta(hours=4)) is None
    assert preview_payload(record, now=now - timedelta(seconds=1)) is None


@pytest.mark.parametrize('ambiguous', [False, True])
def test_preview_weekly_durable_dedup_and_ambiguous_send(store, ambiguous):
    import discord
    async def run():
        now = datetime.now(UTC)
        record = sample(now)
        store.append('research_sheet', 'latest_scan', record['payload'], record['id'])
        payload = preview_payload(record, now=now)
        channel = NS(id=10, send=AsyncMock(return_value=NS(id=20)), fetch_message=AsyncMock(return_value=NS(embeds=[discord.Embed.from_dict(payload)])))
        if ambiguous: channel.send.side_effect = TimeoutError()
        client = NS(checked_public_channel=AsyncMock(return_value=channel))
        config = NS(guild=1, general_channel=10)
        if ambiguous:
            with pytest.raises(TimeoutError): await publish_public_preview(client, store, config, now=now)
        else:
            assert await publish_public_preview(client, store, config, now=now) == 'DELIVERED'
        assert await publish_public_preview(client, store, config, now=now) == 'DUPLICATE'
        channel.send.assert_awaited_once()
    asyncio.run(run())


import httpx
import pytest

from jabazi.discord_announcement import CHANNEL, GUILD, FILENAME, TEXT, announce
from jabazi.discord_migration import READ, SEND, VIEW
from jabazi.persistence.store import Store


@pytest.mark.parametrize('mode', ['allowed', 'blocked', 'ambiguous'])
def test_approved_banner_has_one_everyone_ping_and_no_replay(tmp_path, mode):
    store = Store('sqlite:///' + str(tmp_path / 'announcement.db'), initialize=True)
    posts = []
    row = {'id': '111', 'content': TEXT, 'mention_everyone': True, 'attachments': [{'filename': FILENAME, 'size': 2266074, 'width': 2048}]}
    def handler(req):
        path = req.url.path
        if req.method == 'POST':
            posts.append(req.content)
            assert b'@everyone' in req.content and b'"parse": ["everyone"]' in req.content
            assert b'\x89PNG\r\n\x1a\n' in req.content
            if mode == 'ambiguous': raise httpx.ReadTimeout('uncertain')
            return httpx.Response(200, json=row)
        if path == f'/guilds/{GUILD}': value = {'owner_id': '2'}
        elif path == '/users/@me': value = {'id': '9'}
        elif path == f'/channels/{CHANNEL}': value = {'id': CHANNEL, 'guild_id': GUILD, 'type': 0, 'permission_overwrites': []}
        elif path == f'/guilds/{GUILD}/roles': value = [{'id': GUILD, 'permissions': str(VIEW | READ | SEND | (1 << 15) | (0 if mode == 'blocked' else 1 << 17))}]
        elif path == f'/guilds/{GUILD}/members/9': value = {'roles': []}
        elif path == f'/channels/{CHANNEL}/messages/111': value = row
        else: raise AssertionError(path)
        return httpx.Response(200, json=value)
    try:
        with httpx.Client(base_url='https://discord.test', transport=httpx.MockTransport(handler)) as http:
            if mode == 'ambiguous':
                with pytest.raises(httpx.ReadTimeout): announce(http, store, guild=GUILD, owner='2')
                assert announce(http, store, guild=GUILD, owner='2')['status'] == 'DELIVERY_REQUIRES_REVIEW'
            elif mode == 'blocked':
                assert announce(http, store, guild=GUILD, owner='2')['missing_bits'] == str(1 << 17)
            else:
                assert announce(http, store, guild=GUILD, owner='2')['status'] == 'POSTED_VERIFIED'
                assert announce(http, store, guild=GUILD, owner='2')['status'] == 'VERIFIED_ALREADY_POSTED'
        assert len(posts) == (0 if mode == 'blocked' else 1)
    finally:
        store.close()

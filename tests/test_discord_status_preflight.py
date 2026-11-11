import httpx
import pytest
from jabazi.discord_bot import BotConfig
from tools.check_discord_status_target import inspect_target


@pytest.mark.parametrize('failure', [None, 'deleted', 'public', 'unreviewed'])
def test_read_only_target_preflight_distinguishes_unknown_channel_and_privacy(failure):
    calls = []
    def handle(request):
        calls.append(request.method)
        path = request.url.path
        values = {'/users/@me': {'id': '10'}, '/guilds/1': {'owner_id': '2'},
                  '/guilds/1/members/10': {'roles': []}, '/guilds/1/roles': []}
        if path == '/channels/5':
            if failure == 'deleted':
                return httpx.Response(404, json={'code': 10003, 'message': 'private body'})
            overwrites = [{'id': '1', 'type': 0, 'allow': '0', 'deny': '1024'}]
            if failure == 'public':
                overwrites = []
            if failure == 'unreviewed':
                overwrites.append({'id': '999', 'type': 0, 'allow': '1024', 'deny': '0'})
            return httpx.Response(200, json={'id': '5', 'guild_id': '1', 'type': 0,
                                            'permission_overwrites': overwrites})
        return httpx.Response(200, json=values[path])
    with httpx.Client(base_url='https://example.test', transport=httpx.MockTransport(handle)) as client:
        result = inspect_target(client, BotConfig(1, 2, 3, 4, frozenset()), status_channel=5)
    assert set(calls) == {'GET'}
    assert result['message_sent'] is False and result['configuration_changed'] is False
    assert result['status'] == ('BLOCKED' if failure else 'TARGET_VALIDATED')
    assert 'private body' not in str(result)
    if failure == 'deleted':
        assert result['checks'][-1] == {'resource': 'status_channel', 'http': 404, 'code': 10003}

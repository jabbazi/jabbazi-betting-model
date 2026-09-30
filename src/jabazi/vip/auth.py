"""Live Discord authorization, bounded cache, and fail-closed membership checks."""
import os
import threading
import time

import httpx
from fastapi import HTTPException

from ..discord_access import vip_role_ids

_cache = {}
_lock = threading.Lock()
TTL = 30


def configured(name):
    return {v.strip() for v in os.getenv(name, '').split(',') if v.strip().isdigit()}


def current_access(guild, member):
    key = (str(guild), str(member))
    with _lock:
        saved = _cache.get(key)
        if saved and time.monotonic() - saved[0] < TTL:
            return dict(saved[1])
    token = os.getenv('JABBAZI_DISCORD_BOT_TOKEN', '')
    if not token:
        raise HTTPException(503, 'Discord access verification is temporarily unavailable.')
    try:
        with httpx.Client(base_url='https://discord.com/api/v10', headers={'Authorization': 'Bot ' + token}, timeout=8) as http:
            response = http.get(f'/guilds/{guild}/members/{member}')
            if response.status_code == 404:
                result = {'tier': 'FREE', 'vip': False, 'admin': False}
            else:
                response.raise_for_status()
                roles = http.get(f'/guilds/{guild}/roles')
                roles.raise_for_status()
                actual = set(map(str, response.json().get('roles', [])))
                approved = vip_role_ids(roles.json(), configured('JABBAZI_DISCORD_VIEWER_ROLE_IDS') | configured('JABBAZI_DISCORD_VIP_ROLE_ID'))
                owner = str(member) == os.getenv('JABBAZI_DISCORD_OWNER_ID', '')
                admin = owner or bool(actual & configured('JABBAZI_APP_ADMIN_ROLE_IDS'))
                developer = bool(actual & configured('JABBAZI_APP_DEVELOPER_ROLE_IDS'))
                vip = admin or developer or bool(actual & approved)
                result = {'tier': 'ADMIN' if admin else 'DEVELOPER' if developer else 'VIP' if vip else 'FREE', 'vip': vip, 'admin': admin}
    except httpx.HTTPError:
        # Never reuse an expired success when Discord cannot verify current roles.
        raise HTTPException(503, 'Discord access verification is temporarily unavailable.') from None
    with _lock:
        if len(_cache) >= 5000:
            _cache.clear()
        _cache[key] = (time.monotonic(), result)
    return dict(result)

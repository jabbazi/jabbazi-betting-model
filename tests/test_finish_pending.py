import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from test_member_portal import portal as _portal_fixture, sign_in
from jabazi.persistence.lookup_indexes import ensure_lookup_indexes
from jabazi.vip.delivery import quiet, enabled, deliver_watch_dms

portal = _portal_fixture


def test_indexes_are_idempotent_and_preserve_evidence(portal):
    store, _ = portal
    store.append('scan_run', 'test', {'healthy':True})
    assert ensure_lookup_indexes(store) == ensure_lookup_indexes(store)
    assert store.list_records('scan_run', 1)[0]['payload']['healthy'] is True


def test_today_is_separate_from_fast_shell(portal):
    store, client = portal
    sign_in(store, client)
    assert client.get('/v1/vip/home').json()['load_strategy'] == 'on_demand'
    value = client.get('/v1/vip/today').json()
    assert value['games'] == [] and value['official'] == []
    assert value['recap']['label'] == 'Today'


def test_quiet_hours_cross_midnight_and_dst():
    prefs = {'discord_dm':True, 'quiet_start':22, 'quiet_end':7}
    for instant in ('2026-10-14T04:00:00+00:00','2026-11-01T06:30:00+00:00','2026-11-01T07:30:00+00:00'):
        assert quiet(prefs, datetime.fromisoformat(instant))
    assert not quiet(prefs, datetime.fromisoformat('2026-10-14T12:00:00+00:00'))
    assert not enabled({}, {}, datetime.now(UTC))


def test_dm_requires_opt_in_and_deduplicates_delivery(portal, monkeypatch):
    store, _ = portal
    now = datetime.now(UTC)
    note = {'id':'candidate', 'at':now.isoformat(), 'state':'PRICE TARGET MET', 'price':2.1, 'sport':'MLB'}
    store.append('vip_notification', '1:2', note)
    store.append('vip_watchlist', '1:2', {'items':[{'id':'candidate'}]})
    member=NS(id=2, roles=[], send=AsyncMock(return_value=NS(id=123)))
    guild=NS(fetch_member=AsyncMock(return_value=member))
    client=NS(get_guild=lambda _:guild)
    config=NS(guild=1, owner=2, viewer_roles=[], vip_role=0)
    monkeypatch.setattr('jabazi.vip.delivery.board', lambda _: {'rows':[{'id':'candidate','fresh':True,'data_health':'HEALTHY','status':'WATCH','decimal':2.1,'sport':'MLB','event':'A @ B','selection':'Over','price_at':now.isoformat()}]})
    monkeypatch.setattr('jabazi.vip.delivery.delivery_eligible',lambda *_:True)
    asyncio.run(deliver_watch_dms(client,store,config))
    member.send.assert_not_awaited()
    store.append('vip_preferences','1:2',{'discord_dm':True})
    monkeypatch.setattr('jabazi.vip.delivery.delivery_eligible',lambda *_:False)
    asyncio.run(deliver_watch_dms(client,store,config))
    member.send.assert_not_awaited()
    monkeypatch.setattr('jabazi.vip.delivery.delivery_eligible',lambda *_:True)
    monkeypatch.setattr('jabazi.discord_bot.member_has_vip',lambda *_:False)
    asyncio.run(deliver_watch_dms(client,store,config))
    member.send.assert_not_awaited()
    monkeypatch.setattr('jabazi.discord_bot.member_has_vip',lambda *_:True)
    asyncio.run(deliver_watch_dms(client,store,config))
    asyncio.run(deliver_watch_dms(client,store,config))
    member.send.assert_awaited_once()
    assert store.list_records('vip_dm_receipt',1)[0]['payload']['state']=='SENT'


def test_expired_notifications_never_deliver(portal):
    store, _ = portal
    store.append('vip_notification','1:2',{'id':'old','at':(datetime.now(UTC)-timedelta(minutes=6)).isoformat()})
    store.append('vip_preferences','1:2',{'discord_dm':True})
    client=NS(get_guild=lambda _: (_ for _ in ()).throw(AssertionError('Do not contact Discord')))
    asyncio.run(deliver_watch_dms(client,store,NS(guild=1)))


def test_preferences_reject_partial_quiet_hours(portal):
    store, client = portal
    from jabazi.member_access import portal_origin
    sign_in(store, client)
    assert client.put('/v1/vip/preferences',json={'quiet_start':22},headers={'Origin':portal_origin()}).status_code == 422
    assert client.put('/v1/vip/preferences',json={'quiet_start':22,'quiet_end':7,'discord_dm':True},headers={'Origin':portal_origin()}).status_code == 200

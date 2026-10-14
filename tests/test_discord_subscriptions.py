import asyncio
import copy
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from jabazi.discord_bot import BotConfig, member_has_vip
from jabazi.discord_rules import CONFIG_KEY, configuration, reconcile_member
from jabazi.discord_subscriptions import (WHOP_ALLOWED_PERMISSIONS, WHOP_BOT_ID,
    WHOP_SOURCE_NAME, install_whop_source, paid_source_roles, subscription_sources)
from jabazi.persistence.store import Store


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = Store('sqlite:///' + str(tmp_path/'subscriptions.db'), initialize=True)
    gate = {'status':'ACTIVE','guild':'1','owner':'100','version':'v1',
            'community_role':'3','paid_role':'4','source_vip':['2'],
            'paid_roles':{'2':'6'},'grandfathered':{},'channels':{}}
    store.append('discord_rules_config', CONFIG_KEY, gate)
    monkeypatch.setenv('JABBAZI_WHOP_SETUP_ENABLED','true')
    monkeypatch.setenv('JABBAZI_DISCORD_GUILD_ID','1')
    monkeypatch.setenv('JABBAZI_DISCORD_OWNER_ID','100')
    monkeypatch.setenv('JABBAZI_DISCORD_BOT_TOKEN','synthetic')
    roles = [{'id':'1','name':'@everyone','permissions':'0','position':0},
             {'id':'2','name':'🔮 JABBAZI VIP','permissions':'0','position':6},
             {'id':'3','name':'JABBAZI COMMUNITY','permissions':'0','position':5},
             {'id':'4','name':'JABBAZI VERIFIED VIP','permissions':'0','position':4},
             {'id':'6','name':'JABBAZI VERIFIED 2','permissions':'0','position':3},
             {'id':'8','name':'JABBAZI BOT','permissions':'8','position':7},
             {'id':'9','name':'Whop Bot','permissions':str(WHOP_ALLOWED_PERMISSIONS),
              'position':1,'managed':True,'tags':{'bot_id':WHOP_BOT_ID}}]
    members = [{'user':{'id':str(i)},'roles':['2','3','6']} for i in range(1000,1014)]
    channels = [{'id':'10','permission_overwrites':[
        {'id':'1','type':0,'allow':'0','deny':'1024'},
        {'id':'6','type':0,'allow':'1024','deny':'0'}]}]
    writes = []
    def request(http, method, path, operation, **kwargs):
        if method != 'GET': writes.append((method,path,copy.deepcopy(kwargs)))
        if path == '/guilds/1': return {'owner_id':'100'}
        if path == '/guilds/1/roles':
            if method == 'POST':
                for r in roles:
                    if r['position'] > 0: r['position'] += 1
                roles.append({'id':'20','position':1,**kwargs['json']})
                return copy.deepcopy(roles[-1])
            return copy.deepcopy(roles)
        if path == '/guilds/1/channels': return copy.deepcopy(channels)
        if path.startswith('/guilds/1/members?'): return copy.deepcopy(members)
        raise AssertionError((method,path))
    monkeypatch.setattr('jabazi.discord_subscriptions.request',request)
    monkeypatch.setattr('jabazi.discord_subscriptions.httpx.Client',lambda **kwargs:nullcontext(None))
    yield NS(store=store,gate=gate,roles=roles,members=members,channels=channels,writes=writes)
    store.close()


def test_install_separates_billing_preserves_members_and_is_idempotent(setup):
    before_members = copy.deepcopy(setup.members)
    before_channels = copy.deepcopy(setup.channels)
    result = install_whop_source(setup.store)
    assert result['source_role'] == '20' and result['reference_role'] == '2'
    assert configuration(setup.store)['subscription_sources'] == {'20':'2'}
    assert configuration(setup.store)['paid_roles'] == {'2':'6'}
    assert setup.members == before_members and setup.channels == before_channels
    assert len(setup.store.list_records('whop_setup_backup',20)) == 1
    assert install_whop_source(setup.store) == result
    assert len(setup.writes) == 1 and setup.writes[0][1] == '/guilds/1/roles'
    assert len(setup.store.list_records('discord_rules_config',20)) == 2


@pytest.mark.parametrize('defect', ['broad_bot','unrelated_lower','direct_grant','existing_holder','duplicate','bad_derived'])
def test_unsafe_roles_never_activate_a_subscription_mapping(setup, defect):
    source = {'id':'20','name':WHOP_SOURCE_NAME,'permissions':'0','position':1}
    setup.roles[-1]['position'] = 2
    setup.roles.append(source)
    if defect == 'broad_bot': setup.roles[-2]['permissions'] = str(WHOP_ALLOWED_PERMISSIONS | 8)
    if defect == 'unrelated_lower': setup.roles.append({'id':'21','name':'staff','permissions':'8','position':1})
    if defect == 'direct_grant': setup.channels[0]['permission_overwrites'].append({'id':'20','type':0,'allow':'1024','deny':'0'})
    if defect == 'existing_holder': setup.members[0]['roles'].append('20')
    if defect == 'duplicate': setup.roles.append({**source,'id':'21'})
    if defect == 'bad_derived': next(r for r in setup.roles if r['id']=='6')['permissions']='8'
    with pytest.raises(ValueError): install_whop_source(setup.store)
    assert configuration(setup.store) == setup.gate
    assert setup.writes == []


def test_disabled_setup_has_no_side_effects(setup, monkeypatch):
    monkeypatch.delenv('JABBAZI_WHOP_SETUP_ENABLED')
    assert install_whop_source(setup.store) == {'status':'DISABLED'}
    assert setup.writes == []


def test_subscription_is_rules_gated_and_cancellation_preserves_manual_vip(setup):
    install_whop_source(setup.store)
    gate = configuration(setup.store)
    async def run():
        role = lambda rid: NS(id=rid,name=str(rid),permissions=NS(value=0),managed=False)
        member = NS(id=77,bot=False,joined_at=datetime.now(UTC),roles=[role(20)],
                    guild=NS(id=1,get_role=role))
        async def add(r,**kwargs): member.roles.append(r)
        async def remove(r,**kwargs): member.roles[:] = [x for x in member.roles if x.id != r.id]
        member.add_roles=AsyncMock(side_effect=add);member.remove_roles=AsyncMock(side_effect=remove)
        bot=BotConfig(1,100,30,31,frozenset({2}))
        await reconcile_member(member,setup.store,gate)
        assert [r.id for r in member.roles] == [20]
        assert not member_has_vip(bot,member,setup.store)
        setup.store.append('discord_rules_acceptance','1:77',{'version':'v1','joined_at':member.joined_at.isoformat()})
        await reconcile_member(member,setup.store,gate)
        assert {r.id for r in member.roles} == {20,3,6}
        assert member_has_vip(bot,member,setup.store)
        member.roles.append(role(2)) # Independent owner/manual entitlement.
        member.roles[:] = [r for r in member.roles if r.id != 20] # Whop cancellation.
        await reconcile_member(member,setup.store,gate)
        assert {r.id for r in member.roles} == {2,3,6}
        assert member_has_vip(bot,member,setup.store)
        member.roles[:] = [r for r in member.roles if r.id != 2]
        await reconcile_member(member,setup.store,gate)
        assert {r.id for r in member.roles} == {3}
        assert not member_has_vip(bot,member,setup.store)
        member.roles=[role(20)]
        member.guild=NS(id=99,get_role=role)
        assert not member_has_vip(bot,member,setup.store)
    asyncio.run(run())


def test_only_registered_direct_sources_qualify(setup):
    gate = {**setup.gate,'subscription_sources':{'20':'2','21':'20','3':'2','6':'2','2':'2','22':'99'}}
    assert subscription_sources(gate) == {'20':'2'}
    assert paid_source_roles(gate,{'21'}) == {'21'}
    assert paid_source_roles(gate,{'20'}) == {'20','2'}

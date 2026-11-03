import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from jabazi.discord_rules import (planned_overwrites, accepted, reconcile_member,
                                  rules_view, BUTTON_ID, CONFIG_KEY)
from jabazi.discord_migration import VIEW, READ, SEND, effective_permissions
from jabazi.discord_bot import BotConfig, member_has_vip
from jabazi.persistence.store import Store


@pytest.fixture
def store(tmp_path):
    result=Store('sqlite:///'+str(tmp_path/'gate.db'),initialize=True)
    yield result
    result.close()


def test_gate_requires_both_acceptance_and_paid_role_in_permission_matrix():
    roles=[{'id':str(i),'permissions':str(VIEW|READ|SEND) if i==1 else '0'} for i in (1,2,3,4,5)]
    public={'id':'10','permission_overwrites':[{'id':'1','type':0,'allow':str(VIEW|READ|SEND),'deny':'0'}]}
    private={'id':'11','permission_overwrites':[{'id':'1','type':0,'allow':'0','deny':str(VIEW)}, {'id':'2','type':0,'allow':str(VIEW|READ),'deny':str(SEND)}]}
    for channel in (public,private):
        result={**channel,'permission_overwrites':planned_overwrites(channel,guild='1',source_vip={'2'},trusted=set(),community='3',paid='4',exempt=set())}
        visible=lambda held:bool(effective_permissions('1','99',held,roles,result,'100')&VIEW)
        assert not visible([])
        assert not visible(['2'])  # Purchase alone cannot bypass acceptance.
        assert visible(['3']) == (channel is public)
        assert visible(['2','3','4'])
        if channel is private:
            assert not effective_permissions('1','99',['2','3','4'],roles,result,'100')&SEND
    with pytest.raises(ValueError,match='Unreviewed'):
        planned_overwrites({'id':'10','permission_overwrites':[{'id':'5','type':0,'allow':str(VIEW),'deny':'0'}]},guild='1',source_vip={'2'},trusted=set(),community='3',paid='4',exempt=set())


def gate_config():
    return {'status':'ACTIVE','guild':'1','owner':'100','version':'v1','community_role':'3','paid_role':'4','source_vip':['2'],'grandfathered':{},'channels':{'welcome':'10','rules':'11','guide':'12','general':'13','support':'14','access':'15'}}


def test_grandfathered_join_does_not_approve_rejoin(store):
    conf=gate_config(); conf['grandfathered']['9']='2026-10-01T00:00:00.000000+00:00'
    assert accepted(store,conf,9,'2026-10-01T00:00:00+00:00')
    assert not accepted(store,conf,9,'2026-10-02T00:00:00+00:00')


def test_reconciliation_revokes_only_derived_access(store):
    async def run():
        conf=gate_config(); joined=datetime.now(UTC)
        role=lambda rid:NS(id=rid,permissions=NS(value=0),managed=False)
        guild=NS(id=1,get_role=lambda rid:role(rid))
        member=NS(id=9,bot=False,guild=guild,joined_at=joined,roles=[role(2)],add_roles=AsyncMock(),remove_roles=AsyncMock())
        await reconcile_member(member,store,conf)
        member.add_roles.assert_not_awaited()
        store.append('discord_rules_acceptance','1:9',{'version':'v1','joined_at':joined.isoformat()})
        await reconcile_member(member,store,conf)
        assert [c.args[0].id for c in member.add_roles.call_args_list]==[3,4]
        member.roles=[role(3),role(4)] # Original paid role expired.
        await reconcile_member(member,store,conf)
        assert [c.args[0].id for c in member.remove_roles.call_args_list]==[4]
        member.joined_at=joined+timedelta(days=1) # Genuine rejoin requires acceptance.
        member.remove_roles.reset_mock()
        await reconcile_member(member,store,conf)
        assert [c.args[0].id for c in member.remove_roles.call_args_list]==[3,4]
    asyncio.run(run())


def test_button_is_persistent_idempotent_and_cannot_grant_entitlement(store):
    async def run():
        conf=gate_config(); store.append('discord_rules_config',CONFIG_KEY,conf)
        roles={i:NS(id=i,name=str(i),permissions=NS(value=0),managed=False) for i in (2,3,4)}
        guild=NS(id=1,get_role=lambda rid:roles[rid])
        member=NS(id=9,bot=False,guild=guild,joined_at=datetime.now(UTC),roles=[])
        async def add(role,**kwargs): member.roles.append(role)
        member.add_roles=AsyncMock(side_effect=add);member.remove_roles=AsyncMock()
        guild.fetch_member=AsyncMock(return_value=member)
        interaction=NS(guild_id=1,channel_id=10,guild=guild,user=NS(id=9),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        for _ in range(2): # New view simulates restart.
            view=rules_view(store)
            assert view.is_persistent() and view.children[0].custom_id==BUTTON_ID
            await view.children[0].callback(interaction)
        assert len(store.list_records('discord_rules_acceptance',10))==1
        assert [r.id for r in member.roles]==[3]
        assert not member_has_vip(BotConfig(1,100,20,21,frozenset({2})),member,store)
        interaction.guild_id=99;member.add_roles.reset_mock()
        await rules_view(store).children[0].callback(interaction)
        member.add_roles.assert_not_awaited()
    asyncio.run(run())


def test_failed_role_assignment_never_confirms_success(store):
    async def run():
        conf=gate_config();store.append('discord_rules_config',CONFIG_KEY,conf)
        role=NS(id=3,permissions=NS(value=0),managed=False)
        guild=NS(id=1,get_role=lambda _:role)
        member=NS(id=9,bot=False,guild=guild,joined_at=datetime.now(UTC),roles=[],add_roles=AsyncMock(side_effect=RuntimeError('failure')))
        guild.fetch_member=AsyncMock(return_value=member)
        interaction=NS(guild_id=1,channel_id=10,guild=guild,user=NS(id=9),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        await rules_view(store).children[0].callback(interaction)
        assert 'could not confirm' in interaction.followup.send.call_args.args[0]
    asyncio.run(run())


def test_installer_preserves_members_and_verifies_live_permissions(store, monkeypatch):
    import copy
    from contextlib import nullcontext
    from jabazi.discord_rules import install
    monkeypatch.setenv('JABBAZI_DISCORD_GUILD_ID','1')
    monkeypatch.setenv('JABBAZI_DISCORD_OWNER_ID','100')
    monkeypatch.setenv('JABBAZI_DISCORD_BOT_TOKEN','synthetic')
    for k in ('VIP_ROLE_ID','BILLING_ROLE_ID','VIEWER_ROLE_IDS'):
        monkeypatch.delenv('JABBAZI_DISCORD_'+k,raising=False)
    ids=['1559256056595488799','1554590521970655274','1554590522889339011','1552129273517711421','1554590523921272943','1552043747049738243','1554590518480998440']
    channels={i:{'id':i,'name':i,'type':0,'permission_overwrites':[{'id':'1','type':0,'allow':str(VIEW|READ),'deny':str(SEND)}]} for i in ids}
    channels['11']={'id':'11','type':0,'name':'vip','permission_overwrites':[{'id':'1','type':0,'allow':'0','deny':str(VIEW)},{'id':'2','type':0,'allow':str(VIEW|READ),'deny':str(SEND)}]}
    roles=[{'id':'1','name':'@everyone','permissions':'0'}, {'id':'2','name':'VIP','permissions':'0'}, {'id':'8','name':'BOT','permissions':'8','managed':True}]
    members={'9':{'user':{'id':'9'},'roles':['2'],'joined_at':'2026-10-01T00:00:00+00:00'},'200':{'user':{'id':'200','bot':True},'roles':['8']}}
    info={'owner_id':'100','system_channel_id':ids[5],'system_channel_flags':0,'rules_channel_id':ids[2]}
    onboarding={'enabled':False,'mode':0,'default_channel_ids':[ids[5]],'prompts':[]}
    def request(http,method,path,operation,**kwargs):
        if path=='/guilds/1/onboarding':
            if method=='PUT': onboarding.update(copy.deepcopy(kwargs['json']))
            return copy.deepcopy(onboarding)
        if path=='/users/@me': return {'id':'200'}
        if path=='/guilds/1':
            if method=='PATCH': info.update(kwargs['json'])
            return copy.deepcopy(info)
        if path=='/guilds/1/roles':
            if method=='POST': roles.append({'id':str(len(roles)+20),**kwargs['json']}); return copy.deepcopy(roles[-1])
            return copy.deepcopy(roles)
        if path=='/guilds/1/channels':return copy.deepcopy(list(channels.values()))
        if '/members?' in path:return copy.deepcopy(list(members.values()))
        if '/members/' in path:
            mid=path.split('/')[4]
            if '/roles/' in path: members[mid]['roles'].append(path.split('/')[-1]);return None
            return copy.deepcopy(members[mid])
        if path.startswith('/channels/'):
            cid=path.split('/')[2]
            if method=='PATCH':
                if 'permission_overwrites' in kwargs['json'] and cid==ids[5]:
                    assert cid not in onboarding['default_channel_ids'], 'Discord 350003'
                    assert info['system_channel_id']!=cid, 'System channel must stay readable'
                channels[cid].update(copy.deepcopy(kwargs['json']))
            return copy.deepcopy(channels[cid])
        raise AssertionError(path)
    monkeypatch.setattr('jabazi.discord_rules.request',request)
    monkeypatch.setattr('jabazi.discord_rules.httpx.Client',lambda **kwargs:nullcontext(None))
    result=install(store)
    assert result['status']=='ACTIVE'
    assert '2' in members['9']['roles']
    assert result['community_role'] in members['9']['roles']
    assert result['paid_roles']['2'] in members['9']['roles']
    assert info['system_channel_id']==ids[0] and info['system_channel_flags']&1
    assert not effective_permissions('1','99',['2'],roles,channels['11'],'100')&VIEW
    assert install(store)['status']=='ALREADY_ACTIVE'


def test_separate_paid_tiers_never_expand_inner_circle_access():
    roles=[{'id':str(i),'permissions':'0'} for i in (1,2,3,4,5,6,7)]
    channel={'id':'99','permission_overwrites':[
        {'id':'1','type':0,'allow':'0','deny':str(VIEW)},
        {'id':'2','type':0,'allow':str(VIEW|READ),'deny':str(SEND)},
        {'id':'3','type':0,'allow':str(VIEW|READ|SEND),'deny':'0'}]}
    changed={**channel,'permission_overwrites':planned_overwrites(channel,guild='1',source_vip={'2','3'},trusted=set(),community='4',paid='5',exempt=set(),paid_roles={'2':'6','3':'7'})}
    ordinary=effective_permissions('1','100',['2','4','6'],roles,changed,'999')
    inner=effective_permissions('1','100',['3','4','7'],roles,changed,'999')
    assert ordinary&VIEW and not ordinary&SEND
    assert inner&VIEW and inner&SEND
    for held in (['2'],['3']):
        assert not effective_permissions('1','100',held,roles,changed,'999')&VIEW


def test_separate_paid_tier_reconciliation_preserves_source_roles(store):
    async def run():
        conf=gate_config();conf['paid_roles']={'2':'6','5':'7'}
        role=lambda rid:NS(id=rid,permissions=NS(value=0),managed=False)
        guild=NS(id=1,get_role=lambda rid:role(rid))
        member=NS(id=9,bot=False,guild=guild,joined_at=datetime.now(UTC),roles=[role(2),role(3),role(7)],add_roles=AsyncMock(),remove_roles=AsyncMock())
        store.append('discord_rules_acceptance','1:9',{'version':'v1','joined_at':member.joined_at.isoformat()})
        await reconcile_member(member,store,conf)
        assert [c.args[0].id for c in member.add_roles.call_args_list]==[6]
        assert [c.args[0].id for c in member.remove_roles.call_args_list]==[7]
    asyncio.run(run())

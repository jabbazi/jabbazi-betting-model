"""Durable rules acceptance, separate from paid entitlement source roles."""
from datetime import UTC, datetime
import asyncio
import json
import os

import httpx

from .discord_access import is_staff_name, vip_role_ids
from .discord_migration import (request, effective_permissions, configured_vip_ids,
                                VIEW, READ, MANAGE_ROLES, MANAGE_CHANNELS, ADMIN)
from .persistence.store import digest

VERSION = '2026-10-13-v1'
CONFIG_KEY = 'rules-gate'
COMMUNITY_NAME = 'JABBAZI COMMUNITY'
PAID_NAME = 'JABBAZI VERIFIED VIP'
BUTTON_ID = 'jabbazi:accept-rules:v1'


def configuration(store):
    rows = store.list_records('discord_rules_config', 1, entity=CONFIG_KEY)
    return rows[0]['payload'] if rows and rows[0]['payload'].get('status') == 'ACTIVE' else None


def accepted(store, config, member_id, joined_at=None):
    # Existing members are explicitly grandfathered, not falsely marked as accepting.
    member_id = str(member_id)
    if member_id == str(config['owner']):
        return True
    old = config.get('grandfathered', {}).get(member_id)
    if old and (joined_at is None or datetime.fromisoformat(old) == datetime.fromisoformat(str(joined_at))):
        return True
    rows = store.list_records('discord_rules_acceptance', 1, entity=config['guild']+':'+member_id)
    return bool(rows and rows[0]['payload'].get('version') == config['version'] and
                (joined_at is None or datetime.fromisoformat(rows[0]['payload']['joined_at']) == datetime.fromisoformat(str(joined_at))))


def may_issue_ticket(store, guild, member):
    config = configuration(store)
    return not config or (str(guild) == config['guild'] and accepted(store, config, member))


def planned_overwrites(channel, *, guild, source_vip, trusted, community, paid, exempt):
    """Move existing role grants to gated roles; retain bot/staff/member exceptions."""
    rows = [dict(r) for r in channel.get('permission_overwrites', [])]
    if str(channel['id']) in exempt:
        return rows
    everyone = next((r for r in rows if str(r['id']) == guild and r['type'] == 0), None)
    if everyone is None:
        everyone = {'id':guild,'type':0,'allow':'0','deny':'0'}
        rows.append(everyone)
    was_public = bool(int(everyone['allow']) & VIEW) and not int(everyone['deny']) & VIEW
    public_allow = int(everyone['allow'])
    public_deny = int(everyone['deny'])
    everyone.update(allow=str(public_allow & ~VIEW), deny=str(public_deny | VIEW))
    vip_allow = vip_deny = 0
    for row in rows:
        rid = str(row['id'])
        if row['type'] == 0 and rid in source_vip:
            vip_allow |= int(row['allow'])
            vip_deny |= int(row['deny'])
            row.update(allow=str(int(row['allow']) & ~VIEW), deny=str(int(row['deny']) | VIEW))
        elif row['type'] == 0 and rid not in {guild, community, paid} | trusted and int(row['allow']) & VIEW:
            raise ValueError('Unreviewed role grant in gate scope')
    def upsert(rid, allow, deny):
        nonlocal rows
        rows = [r for r in rows if not (r['type']==0 and str(r['id'])==rid)]
        rows.append({'id':rid,'type':0,'allow':str(allow),'deny':str(deny & ~allow)})
    if was_public:
        upsert(community, public_allow | VIEW | READ, public_deny)
    if vip_allow & VIEW:
        upsert(paid, vip_allow, vip_deny)
    return rows


def install(store):
    """One reviewed rollout, with durable before-state and verified member grants."""
    if configuration(store):
        return {'status':'ALREADY_ACTIVE'}
    guild = os.environ['JABBAZI_DISCORD_GUILD_ID']
    owner = os.environ['JABBAZI_DISCORD_OWNER_ID']
    with httpx.Client(base_url='https://discord.com/api/v10',headers={'Authorization':'Bot '+os.environ['JABBAZI_DISCORD_BOT_TOKEN']},timeout=20) as http:
        info = request(http,'GET',f'/guilds/{guild}','RULES_GUILD')
        if str(info['owner_id']) != owner:
            raise ValueError('Owner mismatch')
        bot = request(http,'GET','/users/@me','RULES_BOT')['id']
        bm = request(http,'GET',f'/guilds/{guild}/members/{bot}','RULES_BOT_MEMBER')
        roles = request(http,'GET',f'/guilds/{guild}/roles','RULES_ROLES')
        channels = request(http,'GET',f'/guilds/{guild}/channels','RULES_CHANNELS')
        bits = effective_permissions(guild,bot,bm['roles'],roles,{'permission_overwrites':[]},owner)
        if not bits & ADMIN and bits & (MANAGE_ROLES|MANAGE_CHANNELS|32) != MANAGE_ROLES|MANAGE_CHANNELS|32:
            raise PermissionError('Bot management permissions missing')
        # IDs came from the read-only live audit, not name guesses.
        ids = {'welcome':'1559256056595488799','rules':'1554590521970655274',
               'guide':'1554590522889339011','support':'1552129273517711421',
               'access':'1554590523921272943','general':'1552043747049738243',
               'category':'1554590518480998440'}
        by_id={str(c['id']):c for c in channels}
        if not all(v in by_id for v in ids.values()):
            raise ValueError('Audited channels no longer exist')
        source_vip=vip_role_ids(roles, configured_vip_ids())
        if not source_vip:
            raise ValueError('No source VIP roles')
        members=[]; after='0'
        for _ in range(20):
            page=request(http,'GET',f'/guilds/{guild}/members?limit=1000&after={after}','RULES_MEMBERS')
            members.extend(page)
            if len(page)<1000: break
            after=str(page[-1]['user']['id'])
        else: raise ValueError('Member inventory exceeds bounded rollout')
        onboarding=request(http,'GET',f'/guilds/{guild}/onboarding','RULES_ONBOARDING')
        backup={'onboarding':onboarding,'channels':channels,'roles':roles,'system_channel_id':info.get('system_channel_id'),
                'system_channel_flags':info.get('system_channel_flags',0),'rules_channel_id':info.get('rules_channel_id'),
                'members':[{'id':m['user']['id'],'roles':m['roles'],'joined_at':m.get('joined_at')} for m in members]}
        key=digest(['discord_rules_backup',guild,backup])
        store.append('discord_rules_backup',guild,backup,key)
        if not any(r['id']==key for r in store.list_records('discord_rules_backup',20,entity=guild)):
            raise RuntimeError('Backup readback failed')
        gate_roles={}
        for name in (COMMUNITY_NAME,PAID_NAME):
            matches=[r for r in roles if r['name']==name]
            if len(matches)>1: raise ValueError('Duplicate gate roles')
            role=matches[0] if matches else request(http,'POST',f'/guilds/{guild}/roles','RULES_CREATE_ROLE',json={'name':name,'permissions':'0','mentionable':False,'hoist':False})
            if role.get('managed') or int(role['permissions']) or str(role['id']) in source_vip:
                raise ValueError('Gate role is not least privilege')
            gate_roles[name]=str(role['id'])
        community,paid=gate_roles[COMMUNITY_NAME],gate_roles[PAID_NAME]
        # Trust staff and integration bot roles already present; do not grant new privileges.
        trusted={str(r['id']) for r in roles if r.get('managed') or is_staff_name(r['name']) or str(r['id']) in bm['roles']}
        exempt={ids[k] for k in ('welcome','rules','guide','support','access','category')}
        plans=[]
        for channel in channels:
            # Existing hidden archives stay hidden; no unrelated archive reorganization.
            perms=channel.get('permission_overwrites',[])
            affected=any(r['type']==0 and str(r['id']) in {guild}|source_vip and int(r['allow'])&VIEW for r in perms)
            if affected and str(channel['id']) not in exempt:
                changes=planned_overwrites(channel,guild=guild,source_vip=source_vip,trusted=trusted,community=community,paid=paid,exempt=exempt)
                plans.append((channel,changes))
        # Preserve the exact pre-rollout joins, including reruns after a partial apply.
        prior=store.list_records('discord_rules_rollout',1,entity=CONFIG_KEY)
        grandfathered=prior[0]['payload']['grandfathered'] if prior else {str(m['user']['id']):m['joined_at'] for m in members if not m['user'].get('bot')}
        config={'status':'ACTIVE','guild':guild,'owner':owner,'version':VERSION,'community_role':community,'paid_role':paid,
                'source_vip':sorted(source_vip),'grandfathered':grandfathered,'channels':ids,'backup_id':key}
        if not prior: store.append('discord_rules_rollout',CONFIG_KEY,config)
        for member in members:
            mid=str(member['user']['id'])
            if mid not in grandfathered or member.get('joined_at')!=grandfathered[mid]: continue
            for rid in [community]+([paid] if set(member['roles'])&source_vip else []):
                if rid not in member['roles']:
                    request(http,'PUT',f'/guilds/{guild}/members/{mid}/roles/{rid}','RULES_PRESERVE_MEMBER')
            current=request(http,'GET',f'/guilds/{guild}/members/{mid}','RULES_VERIFY_MEMBER')
            if community not in current['roles'] or (set(member['roles'])&source_vip and paid not in current['roles']):
                raise RuntimeError('Existing member access preservation failed')
        # Audit new unpaid/paid and accepted unpaid/paid effective visibility before apply.
        virtual_roles=roles+[{'id':community,'permissions':'0'},{'id':paid,'permissions':'0'}]
        for channel,changes in plans:
            proposed={**channel,'permission_overwrites':changes}
            for held in ([],list(source_vip)):
                if effective_permissions(guild,'0',held,virtual_roles,proposed,owner)&VIEW:
                    raise ValueError('Unaccepted member would retain access')
            # A shared paid gate is safe only if source tiers already have
            # equivalent access. Refuse to broaden a narrower paid tier.
            for source in source_vip:
                before=effective_permissions(guild,'0',[source],roles,channel,owner)
                after_paid=effective_permissions(guild,'0',[source,community,paid],virtual_roles,proposed,owner)
                if after_paid & VIEW and (not before & VIEW or after_paid & ~before):
                    raise ValueError('Paid tier permissions differ; separate derived roles required')
            for member in members:
                if member['user'].get('bot'): continue
                mid=str(member['user']['id']); old=member['roles']
                extra=[community]+([paid] if set(old)&source_vip else [])
                before=effective_permissions(guild,mid,old,roles,channel,owner)
                after_perms=effective_permissions(guild,mid,old+extra,virtual_roles,proposed,owner)
                if before&VIEW and not after_perms&VIEW:
                    raise ValueError('Existing member visibility would regress')
        # Disabled native onboarding still constrains referenced channels. Preserve
        # its state and prompts while removing references to channels being gated.
        gated={str(channel['id']) for channel,_ in plans}
        prompts=[]
        for original in onboarding.get('prompts',[]):
            prompt={k:original[k] for k in ('id','type','title','single_select','required','in_onboarding') if k in original}
            options=[]
            for original_option in original.get('options',[]):
                option={k:original_option[k] for k in ('id','title','description','role_ids') if k in original_option}
                option['channel_ids']=[cid for cid in original_option.get('channel_ids',[]) if str(cid) not in gated]
                emoji=original_option.get('emoji') or {}
                option.update(emoji_id=emoji.get('id'),emoji_name=emoji.get('name'),emoji_animated=emoji.get('animated',False))
                options.append(option)
            prompt['options']=options
            prompts.append(prompt)
        defaults=[cid for cid in onboarding.get('default_channel_ids',[]) if str(cid) not in gated]
        if not defaults: defaults=[ids['welcome'],ids['guide'],ids['access']]
        updated={'enabled':onboarding.get('enabled',False),'mode':onboarding.get('mode',0),
                 'default_channel_ids':defaults,'prompts':prompts}
        request(http,'PUT',f'/guilds/{guild}/onboarding','RULES_ONBOARDING_ROUTES',json=updated)
        verified=request(http,'GET',f'/guilds/{guild}/onboarding','RULES_VERIFY_ONBOARDING')
        references=set(map(str,verified.get('default_channel_ids',[])))
        for prompt in verified.get('prompts',[]):
            for option in prompt.get('options',[]): references.update(map(str,option.get('channel_ids',[])))
        if references & gated or verified.get('enabled',False)!=onboarding.get('enabled',False):
            raise RuntimeError('Native onboarding routing verification failed')
        for channel,changes in plans:
            if changes!=channel.get('permission_overwrites',[]):
                request(http,'PATCH',f'/channels/{channel["id"]}','RULES_APPLY_GATE',json={'permission_overwrites':changes})
            live=request(http,'GET',f'/channels/{channel["id"]}','RULES_VERIFY_GATE')
            for held in ([],list(source_vip)):
                if effective_permissions(guild,'0',held,virtual_roles,live,owner)&VIEW:
                    raise RuntimeError('Live gate verification failed')
        # Restore the existing rules channel, preserving its message history.
        # Its archived permissions must become publicly readable and read-only.
        rule_permissions=[dict(r) for r in by_id[ids['welcome']].get('permission_overwrites',[])]
        request(http,'PATCH',f'/channels/{ids["rules"]}','RULES_RESTORE_EXISTING',json={'permission_overwrites':rule_permissions})
        # Move/relabel only onboarding channels; preserve other overwrite sets.
        for key_name,name,pos in [('welcome','👋│welcome',0),('rules','📜│rules',1),('guide','🧭│start-here',2),('support','🆘│support',3)]:
            request(http,'PATCH',f'/channels/{ids[key_name]}','RULES_CHANNEL_LAYOUT',json={'name':name,'parent_id':ids['category'],'position':pos})
        request(http,'PATCH',f'/channels/{ids["category"]}','RULES_CATEGORY',json={'name':'👋 START HERE','position':0})
        request(http,'PATCH',f'/guilds/{guild}','RULES_SYSTEM_ROUTING',json={'system_channel_id':ids['welcome'],'system_channel_flags':int(info.get('system_channel_flags',0))|1,'rules_channel_id':ids['rules']})
        store.append('discord_rules_config',CONFIG_KEY,config)
        print('DISCORD_RULES_INSTALL '+json.dumps({'status':'ACTIVE','channels_changed':len(plans),'existing_members_preserved':len(grandfathered),'community_role':community,'paid_role':paid,'backup_id':key}),flush=True)
        return config


async def reconcile_member(member, store, config):
    if member.bot or str(member.guild.id)!=config['guild']: return
    joined=member.joined_at.isoformat() if member.joined_at else ''
    okay=await asyncio.to_thread(accepted,store,config,member.id,joined)
    held={str(r.id) for r in member.roles}
    is_paid=bool(held & set(config['source_vip']))
    for rid,wanted in ((config['community_role'],okay),(config['paid_role'],okay and is_paid)):
        role=member.guild.get_role(int(rid))
        if role is None or role.permissions.value or role.managed:
            raise ValueError('Configured gate role invalid')
        if wanted and rid not in held:
            await member.add_roles(role,reason='JABBAZI rules acceptance and current entitlement')
        elif not wanted and rid in held:
            await member.remove_roles(role,reason='JABBAZI rules or entitlement no longer satisfied')


def rules_view(store):
    import discord
    class RulesView(discord.ui.View):
        def __init__(self): super().__init__(timeout=None)

        @discord.ui.button(label='I have read the rules',emoji='✅',style=discord.ButtonStyle.success,custom_id=BUTTON_ID)
        async def accept(self,interaction,button):
            await interaction.response.defer(ephemeral=True)
            try:
                config=await asyncio.to_thread(configuration,store)
                if not config or str(interaction.guild_id)!=config['guild'] or interaction.channel_id!=int(config['channels']['welcome']):
                    return await interaction.followup.send('Use the rules button in the JABBAZI welcome channel.',ephemeral=True)
                member=await interaction.guild.fetch_member(interaction.user.id)
                if member.bot or not member.joined_at: raise ValueError('Invalid member')
                key=config['guild']+':'+str(member.id)
                payload={'version':config['version'],'accepted_at':datetime.now(UTC).isoformat(),'joined_at':member.joined_at.isoformat()}
                if not await asyncio.to_thread(accepted,store,config,member.id,payload['joined_at']):
                    from .persistence.store import Conflict
                    try:
                        await asyncio.to_thread(store.append,'discord_rules_acceptance',key,payload,digest(['rules_acceptance',key,payload['version'],payload['joined_at']]))
                    except Conflict:
                        if not await asyncio.to_thread(accepted,store,config,member.id,payload['joined_at']):
                            raise
                await reconcile_member(member,store,config)
                verified=await interaction.guild.fetch_member(member.id)
                if int(config['community_role']) not in {r.id for r in verified.roles}: raise RuntimeError('Role not assigned')
                ids=config['channels']
                await interaction.followup.send(f"✅ Community access unlocked. Start at <#{ids['guide']}>, chat in <#{ids['general']}>, choose notifications with **/alerts**, or get help in <#{ids['support']}>. VIP access remains separate: <#{ids['access']}> and **/vip**.",ephemeral=True)
            except Exception as exc:
                print('DISCORD_RULES_ACCEPT_FAILED_'+type(exc).__name__,flush=True)
                await interaction.followup.send('We could not confirm your access. Please try the button again or contact support. Your paid membership has not been changed.',ephemeral=True)
    return RulesView()


async def ensure_welcome(client, store, config):
    import discord
    from .discord_onboarding import is_introduction
    await ensure_rules_text(client, store, config)
    cid=config['channels']['welcome']
    saved=await asyncio.to_thread(store.list_records,'discord_rules_message',1,entity=cid)
    if saved: return saved[0]['payload']
    channel=await client.fetch_channel(int(cid))
    if str(channel.guild.id)!=config['guild']: raise ValueError('Welcome guild mismatch')
    content=(f"👑 **WELCOME TO JABBAZI**\n\nRead our community rules in <#{config['channels']['rules']}>, "
             "then click **✅ I have read the rules** below to unlock community chats.\n\n"
             "VIP access requires a separate active membership.\n**Built on Edge. Not Hype.**")
    # Reuse an existing bot guide rather than posting another welcome introduction.
    old=None
    async for message in channel.history(limit=50):
        if message.author.id==client.user.id and (is_introduction({'content':message.content,'embeds':[e.to_dict() for e in message.embeds]}) or message.content==content):
            old=message; break
    if old:
        await asyncio.to_thread(store.append,'discord_rules_message_backup',cid,{'message_id':str(old.id),'content':old.content,'embeds':[e.to_dict() for e in old.embeds]})
        sent=await old.edit(content=content,embeds=[],view=rules_view(store),allowed_mentions=discord.AllowedMentions.none())
    else:
        claim=digest(['discord_rules_message',cid,config['version']])
        if not await asyncio.to_thread(store.append,'discord_rules_message_claim',cid,{'status':'CLAIMED'},claim):
            raise RuntimeError('Ambiguous welcome delivery needs inspection')
        sent=await channel.send(content,view=rules_view(store),allowed_mentions=discord.AllowedMentions.none(),nonce=claim[:24])
    verified=await channel.fetch_message(sent.id)
    if verified.content!=content or not verified.components:
        raise RuntimeError('Rules message verification failed')
    if not verified.pinned: await verified.pin(reason='JABBAZI rules acceptance')
    result={'message_id':str(sent.id),'channel_id':cid,'version':config['version']}
    await asyncio.to_thread(store.append,'discord_rules_message',cid,result)
    print('DISCORD_RULES_MESSAGE_VERIFIED '+json.dumps(result),flush=True)
    return result


async def ensure_rules_text(client, store, config):
    import discord
    cid=config['channels']['rules']
    if await asyncio.to_thread(store.list_records,'discord_rules_text',1,entity=cid): return
    channel=await client.fetch_channel(int(cid))
    if str(channel.guild.id)!=config['guild']: raise ValueError('Rules guild mismatch')
    content=("📜 **JABBAZI COMMUNITY RULES**\n\n"
             "• Respect members. No harassment, threats, hate speech, or sharing private information.\n"
             "• No spam, scams, impersonation, or unsolicited promotions.\n"
             "• Use the right channels. Member plays and sprinkles are separate from official JABBAZI picks.\n"
             "• Keep results honest: include losses and do not pass off edited tickets or invented records as real performance.\n"
             "• No guaranteed wins. Research and projections can be wrong; do not chase losses.\n"
             "• Do not redistribute private VIP content. Use support for access or billing problems.\n\n"
             f"Return to <#{config['channels']['welcome']}> and click **✅ I have read the rules**.\n"
             f"Rules version: {config['version']} · JABBAZI 👑")
    existing=None
    async for m in channel.history(limit=50):
        if m.author.id==client.user.id and m.content==content: existing=m;break
    if existing is None:
        claim=digest(['rules_text',cid,config['version']])
        if not await asyncio.to_thread(store.append,'discord_rules_text_claim',cid,{},claim):
            raise RuntimeError('Ambiguous rules text send needs inspection')
        existing=await channel.send(content,allowed_mentions=discord.AllowedMentions.none(),nonce=claim[:24])
    verified=await channel.fetch_message(existing.id)
    if verified.content!=content: raise RuntimeError('Rules text mismatch')
    if not verified.pinned: await verified.pin(reason='JABBAZI community rules')
    await asyncio.to_thread(store.append,'discord_rules_text',cid,{'message_id':str(existing.id),'version':config['version']})

"""Read-only live onboarding inventory; never prints member identities or secrets."""
import json
import os
import httpx
from .discord_migration import request, effective_permissions, VIEW, POSTING
from .persistence.store import digest

VERSION = 'rules-gate-v1'


def audit(store):
    guild = os.environ['JABBAZI_DISCORD_GUILD_ID']
    owner = os.environ['JABBAZI_DISCORD_OWNER_ID']
    with httpx.Client(base_url='https://discord.com/api/v10', headers={'Authorization':'Bot '+os.environ['JABBAZI_DISCORD_BOT_TOKEN']}, timeout=20) as http:
        info = request(http,'GET',f'/guilds/{guild}','GATE_READ_GUILD')
        if str(info['owner_id']) != owner:
            raise ValueError('Owner mismatch')
        bot = request(http,'GET','/users/@me','GATE_READ_BOT')['id']
        member = request(http,'GET',f'/guilds/{guild}/members/{bot}','GATE_READ_BOT_MEMBER')
        roles = request(http,'GET',f'/guilds/{guild}/roles','GATE_READ_ROLES')
        channels = request(http,'GET',f'/guilds/{guild}/channels','GATE_READ_CHANNELS')
        onboarding = http.get(f'/guilds/{guild}/onboarding')
        members = []
        after = '0'
        for _ in range(20):
            page = request(http,'GET',f'/guilds/{guild}/members?limit=1000&after={after}','GATE_READ_MEMBERS')
            members.extend(page)
            if len(page)<1000:
                break
            after = str(page[-1]['user']['id'])
        else:
            raise ValueError('Member inventory exceeds bounded audit')
        snapshot = {'version':VERSION,'guild':guild,'owner':owner,'bot':bot,'bot_roles':member['roles'], 'roles':roles,'channels':channels,
                    'features':info.get('features',[]),'system_channel_id':info.get('system_channel_id'),'system_channel_flags':info.get('system_channel_flags'),
                    'rules_channel_id':info.get('rules_channel_id'), 'members':[{'id':m['user']['id'],'bot':m['user'].get('bot',False),'roles':m['roles'],'joined_at':m.get('joined_at')} for m in members]}
        store.append('discord_gate_audit',VERSION,snapshot)
        result = {k:snapshot[k] for k in ('version','features','system_channel_id','system_channel_flags','rules_channel_id')}
        result.update(member_count=len(members), bot_count=sum(bool(m['user'].get('bot')) for m in members),
                      bot_permissions=effective_permissions(guild,bot,member['roles'],roles,{'permission_overwrites':[]},owner),
                      onboarding_http=onboarding.status_code,onboarding_enabled=onboarding.json().get('enabled') if onboarding.status_code==200 else None,
                      roles=[{k:r.get(k) for k in ('id','name','permissions','position','managed')} for r in roles],
                      channels=[{'id':c['id'],'name':c['name'],'type':c['type'],'parent_id':c.get('parent_id'),'position':c.get('position'),
                                 'public_view':bool(effective_permissions(guild,'0',[],roles,c,owner)&VIEW),
                                 'public_post':bool(effective_permissions(guild,'0',[],roles,c,owner)&POSTING)} for c in channels])
        store.append('discord_gate_audit_result',VERSION,result,digest(['discord_gate_audit_result',result]))
        print('DISCORD_GATE_AUDIT '+json.dumps(result),flush=True)
        return result

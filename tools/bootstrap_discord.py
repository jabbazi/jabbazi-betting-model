"""Idempotent JABBAZI Discord server bootstrap.

Dry-run by default. Use --apply only after reviewing the guild and bot permissions.
It never deletes channels/roles and never grants Discord Administrator.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

VIEW=1<<10
SEND=1<<11
READ_HISTORY=1<<16
MANAGE_MESSAGES=1<<13
MODERATE_MEMBERS=1<<40

API="https://discord.com/api/v10"


def load_blueprint():
    path=Path("docs/discord/server_blueprint.json")
    return json.loads(path.read_text())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    token=os.getenv("JABBAZI_DISCORD_BOT_TOKEN","")
    guild=os.getenv("JABBAZI_DISCORD_GUILD_ID","")
    owner=os.getenv("JABBAZI_DISCORD_OWNER_ID","")
    if not token or not guild.isdigit() or not owner.isdigit():
        raise SystemExit("Discord token, guild ID and owner ID are required")
    bp=load_blueprint()
    headers={"Authorization":"Bot "+token,"User-Agent":"JABBAZI-GURU/1.0"}
    with httpx.Client(base_url=API,headers=headers,timeout=20) as http:
        info=http.get(f"/guilds/{guild}").raise_for_status().json()
        if str(info["owner_id"])!=owner:
            raise SystemExit("Configured Discord owner does not own target guild")
        existing_roles=http.get(f"/guilds/{guild}/roles").raise_for_status().json()
        roles={r["name"]:r for r in existing_roles}
        plan={"create_roles":[],"create_categories":[],"create_channels":[]}
        for spec in bp["roles"]:
            if spec["name"] not in roles:
                plan["create_roles"].append(spec["name"])
                if args.apply:
                    payload={
                        "name":spec["name"],"color":spec["color"],"hoist":spec["hoist"],
                        "mentionable":False,"permissions":"0",
                    }
                    roles[spec["name"]]=http.post(
                        f"/guilds/{guild}/roles",json=payload
                    ).raise_for_status().json()
        channels=http.get(f"/guilds/{guild}/channels").raise_for_status().json()
        by_name={(c["name"],c["type"]):c for c in channels}
        def overwrites(access):
            everyone={"id":guild,"type":0,"allow":"0","deny":str(VIEW)}
            if access=="public":
                everyone={"id":guild,"type":0,"allow":str(VIEW|READ_HISTORY),"deny":"0"}
                return [everyone]
            allowed=["VIP","FOUNDING VIP","TRIAL VIP"]
            if access=="staff":
                allowed=["JABBAZI TEAM","MODERATOR"]
            rows=[everyone,{"id":owner,"type":1,"allow":str(VIEW|SEND|READ_HISTORY),"deny":"0"}]
            for name in allowed:
                if name in roles:
                    rows.append({
                        "id":roles[name]["id"],"type":0,
                        "allow":str(VIEW|SEND|READ_HISTORY),"deny":"0",
                    })
            return rows
        for category in bp["categories"]:
            key=(category["name"],4)
            parent=by_name.get(key)
            if parent is None:
                plan["create_categories"].append(category["name"])
                if args.apply:
                    parent=http.post(f"/guilds/{guild}/channels",json={
                        "name":category["name"],"type":4,
                        "permission_overwrites":overwrites(category["access"]),
                    }).raise_for_status().json()
                    by_name[key]=parent
            for name in category["channels"]:
                key=(name,0)
                if key in by_name:
                    continue
                plan["create_channels"].append(name)
                if args.apply:
                    if parent is None:
                        raise RuntimeError("Category must exist before channel creation")
                    by_name[key]=http.post(f"/guilds/{guild}/channels",json={
                        "name":name,"type":0,"parent_id":parent["id"],
                        "permission_overwrites":overwrites(category["access"]),
                        "rate_limit_per_user":5 if name in {"general","sports-talk","bet-talk"} else 0,
                    }).raise_for_status().json()
        try:
            automod=http.get(f"/guilds/{guild}/auto-moderation/rules").raise_for_status().json()
        except httpx.HTTPStatusError:
            automod=[]
        if not any(rule.get("name")=="JABBAZI Mention Spam" for rule in automod):
            plan["automod"]=["JABBAZI Mention Spam"]
            if args.apply:
                http.post(f"/guilds/{guild}/auto-moderation/rules",json={
                    "name":"JABBAZI Mention Spam",
                    "event_type":1,
                    "trigger_type":5,
                    "trigger_metadata":{
                        "mention_total_limit":5,
                        "mention_raid_protection_enabled":True,
                    },
                    "actions":[{"type":1,"metadata":{"custom_message":"Please avoid mass mentions."}}],
                    "enabled":True,
                    "exempt_roles":[],
                    "exempt_channels":[],
                }).raise_for_status()
        else:
            plan["automod"]=[]
        print(json.dumps({
            "mode":"APPLIED" if args.apply else "DRY_RUN",
            "guild_id":guild,
            "plan":plan,
            "note":"No existing role/channel was deleted or overwritten.",
        },indent=2))


if __name__=="__main__":
    main()

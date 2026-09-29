"""Idempotent live Discord structure/permission reconciliation."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

VIEW=1<<10
SEND=1<<11
READ_HISTORY=1<<16
API="https://discord.com/api/v10"
VIP_NAMES={"VIP","JABBAZI VIP","FOUNDING VIP","TRIAL VIP"}


def is_vip_name(name):
    return "VIP" in str(name or "").strip().upper()
STAFF_NAMES={"JABBAZI TEAM","MODERATOR"}


def reconcile():
    token=os.getenv("JABBAZI_DISCORD_BOT_TOKEN","")
    guild=os.getenv("JABBAZI_DISCORD_GUILD_ID","")
    owner=os.getenv("JABBAZI_DISCORD_OWNER_ID","")
    if not token or not guild.isdigit() or not owner.isdigit():
        return {"status":"UNCONFIGURED"}
    blueprint=json.loads(Path("docs/discord/server_blueprint.json").read_text())
    headers={"Authorization":"Bot "+token,"User-Agent":"JABBAZI-GURU/2.0"}
    summary={"created":0,"repaired":0,"hidden":0}
    with httpx.Client(base_url=API,headers=headers,timeout=20) as http:
        info=http.get(f"/guilds/{guild}").raise_for_status().json()
        if str(info["owner_id"])!=owner:
            raise ValueError("Discord owner mismatch")
        roles_list=http.get(f"/guilds/{guild}/roles").raise_for_status().json()
        roles={str(r["name"]).strip().upper():r for r in roles_list}
        # Preserve and use the guild's existing VIP-named roles; do not require
        # permission to create/rename roles merely to repair channel access.
        vip_roles=[role for role in roles_list if is_vip_name(role.get("name"))]
        if not vip_roles:
            return {"status":"NO_VIP_ROLE","created":0,"repaired":0,"hidden":0}
        channels=http.get(f"/guilds/{guild}/channels").raise_for_status().json()
        by_name={(c["name"],c["type"]):c for c in channels}

        def overwrites(access):
            if access=="public":
                return [{"id":guild,"type":0,"allow":str(VIEW|READ_HISTORY),"deny":"0"}]
            allowed=VIP_NAMES if access=="vip" else STAFF_NAMES
            rows=[
                {"id":guild,"type":0,"allow":"0","deny":str(VIEW)},
                {"id":owner,"type":1,"allow":str(VIEW|SEND|READ_HISTORY),"deny":"0"},
            ]
            selected_roles = (
                vip_roles
                if access == "vip"
                else [roles[name] for name in allowed if name in roles]
            )
            for role in selected_roles:
                rows.append({
                    "id":role["id"],"type":0,
                    "allow":str(VIEW|SEND|READ_HISTORY),"deny":"0",
                })
            return rows

        for category in blueprint["categories"]:
            access=category["access"]
            desired=overwrites(access)
            key=(category["name"],4)
            parent=by_name.get(key)
            if parent is None:
                parent=http.post(f"/guilds/{guild}/channels",json={
                    "name":category["name"],"type":4,"permission_overwrites":desired,
                }).raise_for_status().json()
                by_name[key]=parent
                summary["created"]+=1
            else:
                http.patch(f"/channels/{parent['id']}",json={
                    "permission_overwrites":desired,
                }).raise_for_status()
                summary["repaired"]+=1
            for name in category["channels"]:
                key=(name,0)
                channel=by_name.get(key)
                payload={
                    "parent_id":parent["id"],
                    "permission_overwrites":desired,
                    "rate_limit_per_user":5 if name in {"general","sports-talk"} else 0,
                }
                if channel is None:
                    channel=http.post(f"/guilds/{guild}/channels",json={
                        "name":name,"type":0,**payload,
                    }).raise_for_status().json()
                    by_name[key]=channel
                    summary["created"]+=1
                else:
                    http.patch(f"/channels/{channel['id']}",json=payload).raise_for_status()
                    summary["repaired"]+=1

        keep={name for category in blueprint["categories"] for name in category["channels"]}
        for name in blueprint.get("deprecated_channels",[]):
            channel=by_name.get((name,0))
            if channel is None or name in keep:
                continue
            http.patch(f"/channels/{channel['id']}",json={
                "permission_overwrites":[
                    {"id":guild,"type":0,"allow":"0","deny":str(VIEW)},
                    {"id":owner,"type":1,"allow":str(VIEW|SEND|READ_HISTORY),"deny":"0"},
                ],
            }).raise_for_status()
            summary["hidden"]+=1
    return {"status":"RECONCILED",**summary}

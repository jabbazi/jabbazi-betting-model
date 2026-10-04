"""Least-privilege Discord VIP role synchronization."""
from __future__ import annotations

import os
import httpx

from .discord_entitlements import latest_entitlement

API="https://discord.com/api/v10"


def configured():
    token=os.getenv("JABBAZI_DISCORD_BOT_TOKEN","")
    guild=os.getenv("JABBAZI_DISCORD_GUILD_ID","")
    role=os.getenv("JABBAZI_DISCORD_BILLING_ROLE_ID","")
    manual_roles = {os.getenv("JABBAZI_DISCORD_VIP_ROLE_ID", "")}
    manual_roles.update(os.getenv("JABBAZI_DISCORD_VIEWER_ROLE_IDS", "").split(","))
    return bool(token and guild.isdigit() and role.isdigit() and role not in manual_roles)


def sync_member_role(store, member_id):
    if not configured():
        return {"status":"UNCONFIGURED"}
    member=str(member_id)
    if not member.isdigit():
        raise ValueError("Valid Discord member ID required")
    token=os.environ["JABBAZI_DISCORD_BOT_TOKEN"]
    guild=os.environ["JABBAZI_DISCORD_GUILD_ID"]
    role=os.environ["JABBAZI_DISCORD_BILLING_ROLE_ID"]
    entitlement=latest_entitlement(store,member)
    if entitlement is None:
        return {"status": "NO_BILLING_RECORD", "member_id": member}
    active=bool(entitlement["active"])
    method="PUT" if active else "DELETE"
    with httpx.Client(
        base_url=API,
        headers={"Authorization":"Bot "+token,"User-Agent":"JABBAZI-GURU/1.0"},
        timeout=15,
    ) as http:
        response=http.request(method,f"/guilds/{guild}/members/{member}/roles/{role}")
        if response.status_code == 404:
            return {"status": "MEMBER_OR_ROLE_UNAVAILABLE", "member_id": member}
        response.raise_for_status()
    return {"status":"VIP_GRANTED" if active else "VIP_REMOVED","member_id":member}


def reconcile_known(store, limit=1000):
    if not configured():
        return {"status": "UNCONFIGURED", "granted": 0, "removed": 0, "errors": 0}
    rows=store.list_records("discord_entitlement",limit)
    members=[]
    seen=set()
    for row in rows:
        member=str(row["payload"].get("member_id") or "")
        if member.isdigit() and member not in seen:
            seen.add(member); members.append(member)
    results={"granted":0,"removed":0,"errors":0}
    for member in members:
        try:
            status=sync_member_role(store,member)["status"]
            if status=="VIP_GRANTED": results["granted"]+=1
            elif status=="VIP_REMOVED": results["removed"]+=1
        except Exception:  # noqa: BLE001 -- never expose token-bearing provider errors
            results["errors"]+=1
    return results

"""One-shot public identity rebrand for the JABBAZI Discord.

Preserves role IDs and role permissions. It changes only the guild name and the
display names of known JABBAZI-owned roles. Third-party managed roles are untouched.
A durable before/after receipt is stored when the platform database is configured.
"""
from __future__ import annotations

import json
import os
import time

import httpx

from jabazi.discord_access import normalize_role_name
from jabazi.persistence.store import Store, digest

API = "https://discord.com/api/v10"
TARGET_GUILD_NAME = "JABBAZI 👑"

ALERT_DISPLAY = {
    "NFL ALERTS": "🏈 NFL Alerts",
    "CFB ALERTS": "🎓 CFB Alerts",
    "NBA ALERTS": "🏀 NBA Alerts",
    "MLB ALERTS": "⚾ MLB Alerts",
    "NHL ALERTS": "🏒 NHL Alerts",
    "SOCCER ALERTS": "⚽ Soccer Alerts",
    "TENNIS ALERTS": "🎾 Tennis Alerts",
    "COMBAT ALERTS": "🥊 Combat Alerts",
    "MAIN CARD ALERTS": "👑 Main Card Alerts",
    "PARLAY ALERTS": "🎲 Parlay Alerts",
    "LIVE ALERTS": "🚨 Live Alerts",
    "PROMO ALERTS": "✨ Promo Alerts",
    "CHEAT SHEET ALERTS": "📊 Cheat Sheet Alerts",
}

ROLE_DISPLAY = {
    "JABBAZI TEAM": "🛡️ JABBAZI TEAM",
    "MODERATOR": "⚔️ MODERATOR",
    "FOUNDING VIP": "💎 INNER CIRCLE",
    "INNER CIRCLE": "💎 INNER CIRCLE",
    "FREE MEMBER": "🎟️ MEMBER",
    "MEMBER": "🎟️ MEMBER",
    "TRIAL VIP": "🌱 TRIAL VIP",
}


def request(http, method, path, operation, payload=None):
    for attempt in range(4):
        response = http.request(method, path, json=payload)
        if response.status_code != 429:
            break
        delay = min(float(response.json().get("retry_after", 1)), 10)
        if attempt < 3:
            time.sleep(max(0.2, delay))
    if response.status_code >= 400:
        raise RuntimeError(f"JABBAZI_REBRAND_{operation}_HTTP_{response.status_code}")
    return response.json() if response.content else None


def configured_role_ids():
    values = {
        "billing": os.getenv("JABBAZI_DISCORD_BILLING_ROLE_ID", "").strip(),
        "vip": os.getenv("JABBAZI_DISCORD_VIP_ROLE_ID", "").strip(),
    }
    return {k: v for k, v in values.items() if v.isdigit()}


def rebrand():
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    db = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "").strip()
    if not token or not guild.isdigit() or not owner.isdigit():
        raise RuntimeError("JABBAZI_REBRAND_CONFIGURATION_MISSING")

    headers = {
        "Authorization": "Bot " + token,
        "Content-Type": "application/json",
        "User-Agent": "JABBAZI-Rebrand/1.0",
    }
    with httpx.Client(base_url=API, headers=headers, timeout=20.0) as http:
        info = request(http, "GET", f"/guilds/{guild}", "READ_GUILD")
        if str(info.get("owner_id")) != owner:
            raise RuntimeError("JABBAZI_REBRAND_OWNER_MISMATCH")
        roles = request(http, "GET", f"/guilds/{guild}/roles", "READ_ROLES")

        snapshot = {
            "guild_name": info.get("name"),
            "roles": [
                {
                    "id": str(r["id"]),
                    "name": r.get("name"),
                    "managed": bool(r.get("managed")),
                    "permissions": str(r.get("permissions", "0")),
                    "position": r.get("position"),
                }
                for r in roles
            ],
        }
        backup_id = None
        store = None
        if db:
            store = Store(db)
            if not store.ready():
                raise RuntimeError("JABBAZI_REBRAND_BACKUP_DATABASE_NOT_READY")
            backup_id = digest(["discord_public_rebrand_backup", guild, snapshot])
            store.append("discord_public_rebrand_backup", guild, snapshot, backup_id)
            saved = store.list_records("discord_public_rebrand_backup", 5, entity=guild)
            if not any(row["id"] == backup_id for row in saved):
                raise RuntimeError("JABBAZI_REBRAND_BACKUP_VERIFY_FAILED")

        actions = []
        try:
            if info.get("name") != TARGET_GUILD_NAME:
                updated = request(
                    http, "PATCH", f"/guilds/{guild}", "RENAME_GUILD",
                    {"name": TARGET_GUILD_NAME},
                )
                actions.append({"kind": "guild", "name": updated.get("name")})

            configured = configured_role_ids()
            primary_vip = configured.get("billing") or configured.get("vip")
            desired = {}
            for role in roles:
                if role.get("managed"):
                    continue
                rid = str(role["id"])
                normalized = normalize_role_name(role.get("name"))
                target = ALERT_DISPLAY.get(normalized) or ROLE_DISPLAY.get(normalized)
                if primary_vip and rid == primary_vip:
                    target = "🔮 JABBAZI VIP"
                elif normalized in {"VIP", "JABBAZI VIP"} and not primary_vip:
                    target = "🔮 JABBAZI VIP"
                if target and role.get("name") != target:
                    desired[rid] = target

            # Never create duplicate display names. Configured role IDs remain
            # authoritative even when a secondary legacy VIP role keeps its old name.
            for rid, target in list(desired.items()):
                conflicts = [
                    r for r in roles
                    if str(r["id"]) != rid and r.get("name") == target
                ]
                if conflicts:
                    del desired[rid]

            for rid, target in desired.items():
                before = next(r for r in roles if str(r["id"]) == rid)
                result = request(
                    http, "PATCH", f"/guilds/{guild}/roles/{rid}",
                    "RENAME_ROLE", {"name": target},
                )
                if str(result["id"]) != rid:
                    raise RuntimeError("JABBAZI_REBRAND_ROLE_ID_CHANGED")
                if str(result.get("permissions", "0")) != str(before.get("permissions", "0")):
                    raise RuntimeError("JABBAZI_REBRAND_ROLE_PERMISSIONS_CHANGED")
                actions.append({"kind": "role", "id": rid, "name": target})

            live_info = request(http, "GET", f"/guilds/{guild}", "VERIFY_GUILD")
            live_roles = request(http, "GET", f"/guilds/{guild}/roles", "VERIFY_ROLES")
            if live_info.get("name") != TARGET_GUILD_NAME:
                raise RuntimeError("JABBAZI_REBRAND_GUILD_VERIFY_FAILED")
            by_id = {str(r["id"]): r for r in live_roles}
            for rid, target in desired.items():
                if by_id.get(rid, {}).get("name") != target:
                    raise RuntimeError("JABBAZI_REBRAND_ROLE_VERIFY_FAILED")

            result = {
                "status": "VERIFIED",
                "guild_name": live_info.get("name"),
                "backup_id": backup_id,
                "actions": actions,
                "role_count": len(live_roles),
            }
            if store:
                store.append(
                    "discord_public_rebrand_receipt", guild, result,
                    digest(["discord_public_rebrand_receipt", guild, result]),
                )
            return result
        finally:
            if store:
                store.close()


def main():
    try:
        result = rebrand()
        print("JABBAZI_REBRAND " + json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(
            "JABBAZI_REBRAND "
            + json.dumps(
                {"status": "UNAVAILABLE", "error": str(exc)[:300]},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

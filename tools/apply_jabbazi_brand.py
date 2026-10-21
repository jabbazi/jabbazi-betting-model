"""One-shot public-facing JABBAZI Discord brand pass.

Runs after the backup-first channel migration. It preserves role IDs and never
touches third-party managed bot roles.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

API = "https://discord.com/api/v10"
SERVER_NAME = "JABBAZI 👑"
OWNER_ROLE = "👑 JABBAZI"

ROLE_RENAMES = {
    "JABBAZI TEAM": "🛡️ JABBAZI TEAM",
    "MODERATOR": "⚔️ MODERATOR",
    "FOUNDING VIP": "💎 INNER CIRCLE",
    "FREE MEMBER": "🎟️ MEMBER",
    "TRIAL VIP": "🌱 TRIAL VIP",
    "JABBAZI GURU VIP ACCESS": "🔮 JABBAZI VIP",
}

ALERT_RENAMES = {
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
    "CHEAT SHEET ALERTS": "📊 Cheat Sheet Alerts",
    "PROMO ALERTS": "✨ Promo Alerts",
}


def normalize(name):
    return re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper()).strip()


def request(http, method, path, operation, **kwargs):
    for attempt in range(4):
        response = http.request(method, path, **kwargs)
        if response.status_code != 429:
            break
        if attempt == 3:
            raise RuntimeError("BRAND_RATE_LIMIT_PERSISTED")
        time.sleep(min(float(response.json().get("retry_after", 1)), 10))
    if response.status_code >= 400:
        raise RuntimeError(f"BRAND_{operation}_HTTP_{response.status_code}")
    return response.json() if response.content else None


def main():
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    billing_role = os.getenv("JABBAZI_DISCORD_BILLING_ROLE_ID", "").strip()
    vip_role = os.getenv("JABBAZI_DISCORD_VIP_ROLE_ID", "").strip()
    if not token or not guild.isdigit() or not owner.isdigit():
        raise SystemExit("JABBAZI Discord configuration missing")

    result = {
        "server": "UNVERIFIED",
        "owner_role": "UNVERIFIED",
        "bot_nickname": "UNVERIFIED",
        "roles": [],
        "warnings": [],
    }
    headers = {"Authorization": "Bot " + token, "User-Agent": "JabbaziBrand/1.0"}
    with httpx.Client(base_url=API, headers=headers, timeout=20) as http:
        info = request(http, "GET", f"/guilds/{guild}", "READ_GUILD")
        if str(info.get("owner_id")) != owner:
            raise RuntimeError("BRAND_OWNER_MISMATCH")

        try:
            updated = request(
                http, "PATCH", f"/guilds/{guild}", "RENAME_SERVER",
                json={"name": SERVER_NAME},
            )
            result["server"] = "VERIFIED" if updated.get("name") == SERVER_NAME else "MISMATCH"
        except RuntimeError as exc:
            result["server"] = "ACTION_REQUIRED"
            result["warnings"].append(str(exc))

        roles = request(http, "GET", f"/guilds/{guild}/roles", "READ_ROLES")
        bot = request(http, "GET", "/users/@me", "READ_BOT")
        membership = request(http, "GET", f"/guilds/{guild}/members/{bot['id']}", "READ_BOT_MEMBER")
        bot_role_positions = [
            int(r.get("position", 0))
            for r in roles
            if str(r["id"]) in {str(x) for x in membership.get("roles", [])}
        ]
        bot_top = max(bot_role_positions, default=0)

        # Resolve target role names without changing IDs.
        desired_by_id = {}
        for role in roles:
            if role.get("managed"):
                continue
            key = normalize(role.get("name"))
            if key in ROLE_RENAMES:
                desired_by_id[str(role["id"])] = ROLE_RENAMES[key]
            if key in ALERT_RENAMES:
                desired_by_id[str(role["id"])] = ALERT_RENAMES[key]

        # The billing entitlement role is the authoritative normal paid VIP role.
        if billing_role.isdigit():
            role = next((r for r in roles if str(r["id"]) == billing_role and not r.get("managed")), None)
            if role:
                desired_by_id[billing_role] = "🔮 JABBAZI VIP"
        elif vip_role.isdigit():
            role = next((r for r in roles if str(r["id"]) == vip_role and not r.get("managed")), None)
            if role and normalize(role.get("name")) in {"VIP", "JABBAZI VIP", "JABBAZI GURU VIP ACCESS"}:
                desired_by_id[vip_role] = "🔮 JABBAZI VIP"

        for role in roles:
            rid = str(role["id"])
            desired = desired_by_id.get(rid)
            if not desired or role.get("name") == desired:
                continue
            if int(role.get("position", 0)) >= bot_top:
                result["warnings"].append(f"ROLE_HIERARCHY_BLOCKED:{rid}")
                continue
            try:
                changed = request(
                    http, "PATCH", f"/guilds/{guild}/roles/{rid}", "RENAME_ROLE",
                    json={"name": desired},
                )
                result["roles"].append({
                    "id": rid,
                    "from": role.get("name"),
                    "to": desired,
                    "status": "VERIFIED" if changed.get("name") == desired else "MISMATCH",
                })
            except RuntimeError as exc:
                result["roles"].append({"id": rid, "to": desired, "status": "ACTION_REQUIRED"})
                result["warnings"].append(str(exc))

        # Founder display role: zero permissions, branding only.
        roles = request(http, "GET", f"/guilds/{guild}/roles", "REREAD_ROLES")
        owner_role = next(
            (r for r in roles if not r.get("managed") and normalize(r.get("name")) == "JABBAZI"),
            None,
        )
        if owner_role is None:
            try:
                owner_role = request(
                    http, "POST", f"/guilds/{guild}/roles", "CREATE_OWNER_ROLE",
                    json={
                        "name": OWNER_ROLE,
                        "permissions": "0",
                        "color": 0x8B35E8,
                        "hoist": True,
                        "mentionable": False,
                    },
                )
            except RuntimeError as exc:
                result["warnings"].append(str(exc))
        elif owner_role.get("name") != OWNER_ROLE and int(owner_role.get("position", 0)) < bot_top:
            try:
                owner_role = request(
                    http, "PATCH", f"/guilds/{guild}/roles/{owner_role['id']}",
                    "STYLE_OWNER_ROLE", json={"name": OWNER_ROLE, "hoist": True},
                )
            except RuntimeError as exc:
                result["warnings"].append(str(exc))

        if owner_role:
            try:
                request(
                    http, "PUT",
                    f"/guilds/{guild}/members/{owner}/roles/{owner_role['id']}",
                    "ASSIGN_OWNER_ROLE",
                )
                owner_member = request(http, "GET", f"/guilds/{guild}/members/{owner}", "VERIFY_OWNER_ROLE")
                result["owner_role"] = (
                    "VERIFIED" if str(owner_role["id"]) in {str(x) for x in owner_member.get("roles", [])}
                    else "MISMATCH"
                )
            except RuntimeError as exc:
                result["owner_role"] = "ACTION_REQUIRED"
                result["warnings"].append(str(exc))

        # Optional zero-permission community recognition roles; never auto-assigned.
        roles = request(http, "GET", f"/guilds/{guild}/roles", "READ_OPTIONAL_ROLES")
        for desired in ("⚡ SHARP", "🌱 ROOKIE"):
            if any(normalize(r.get("name")) == normalize(desired) for r in roles if not r.get("managed")):
                continue
            try:
                created = request(
                    http, "POST", f"/guilds/{guild}/roles", "CREATE_COMMUNITY_ROLE",
                    json={"name": desired, "permissions": "0", "hoist": False, "mentionable": False},
                )
                result["roles"].append({"id": str(created["id"]), "to": desired, "status": "VERIFIED"})
            except RuntimeError as exc:
                result["warnings"].append(str(exc))

        try:
            changed = request(
                http, "PATCH", f"/guilds/{guild}/members/@me",
                "BOT_NICKNAME", json={"nick": "JABBAZI SYSTEM"},
            )
            result["bot_nickname"] = (
                "VERIFIED" if changed.get("nick") == "JABBAZI SYSTEM" else "MISMATCH"
            )
        except RuntimeError as exc:
            result["bot_nickname"] = "ACTION_REQUIRED"
            result["warnings"].append(str(exc))

        # Final public-facing name and role readback.
        final_info = request(http, "GET", f"/guilds/{guild}", "VERIFY_GUILD")
        if result["server"] != "ACTION_REQUIRED":
            result["server"] = "VERIFIED" if final_info.get("name") == SERVER_NAME else "MISMATCH"

    print("JABBAZI_BRAND_VERIFICATION " + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

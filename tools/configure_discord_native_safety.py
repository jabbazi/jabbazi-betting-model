"""One-shot native Discord safety configuration for JABBAZI.

Configures conservative Discord AutoMod rules when the JABBAZI bot has Manage
Server. It never grants permissions, changes member roles, or weakens existing
rules. Community Onboarding/Server Guide readiness is audited but not rewritten,
because those surfaces require server-owner UX choices in Discord.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

API = "https://discord.com/api/v10"
ADMIN = 1 << 3
MANAGE_GUILD = 1 << 5
TARGET_RULES = {
    "JABBAZI • Mention Spam": {
        "event_type": 1,
        "trigger_type": 5,
        "trigger_metadata": {
            "mention_total_limit": 5,
            "mention_raid_protection_enabled": True,
        },
    },
    "JABBAZI • Spam Protection": {
        "event_type": 1,
        "trigger_type": 3,
        "trigger_metadata": {},
    },
}


def normalize(value):
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def request(http, method, path, operation, **kwargs):
    for attempt in range(4):
        response = http.request(method, path, **kwargs)
        if response.status_code != 429:
            return response
        if attempt == 3:
            break
        try:
            delay = min(float(response.json().get("retry_after", 1)), 10)
        except Exception:
            delay = 1
        time.sleep(max(0.25, delay))
    raise RuntimeError(operation + "_RATE_LIMIT")


def checked(http, method, path, operation, **kwargs):
    response = request(http, method, path, operation, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{operation}_HTTP_{response.status_code}")
    return response.json() if response.content else None


def configure():
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    bot_log = os.getenv("JABBAZI_DISCORD_BOT_LOG_CHANNEL_ID", "").strip()
    if not token or not guild.isdigit() or not owner.isdigit():
        raise RuntimeError("CONFIGURATION_MISSING")

    headers = {"Authorization": "Bot " + token, "User-Agent": "JabbaziNativeSafety/1.0"}
    result = {
        "status": "APPLYING",
        "community": "UNVERIFIED",
        "automod": [],
        "onboarding": "UNVERIFIED",
        "server_guide": "OWNER_UI_REQUIRED",
        "warnings": [],
    }
    with httpx.Client(base_url=API, headers=headers, timeout=20) as http:
        info = checked(http, "GET", f"/guilds/{guild}", "READ_GUILD")
        if str(info.get("owner_id")) != owner:
            raise RuntimeError("OWNER_MISMATCH")
        result["community"] = "ENABLED" if "COMMUNITY" in set(info.get("features") or []) else "DISABLED"

        me = checked(http, "GET", "/users/@me", "READ_BOT")
        member = checked(http, "GET", f"/guilds/{guild}/members/{me['id']}", "READ_BOT_MEMBER")
        roles = checked(http, "GET", f"/guilds/{guild}/roles", "READ_ROLES")
        selected = {guild, *(str(v) for v in member.get("roles", []))}
        permissions = 0
        for role in roles:
            if str(role["id"]) in selected:
                permissions |= int(role.get("permissions", "0"))
        can_manage = bool(permissions & (ADMIN | MANAGE_GUILD))

        staff_ids = [
            str(r["id"]) for r in roles
            if not r.get("managed") and normalize(r.get("name")) in {"JABBAZI TEAM", "MODERATOR", "JABBAZI"}
        ]

        if can_manage:
            existing = checked(http, "GET", f"/guilds/{guild}/auto-moderation/rules", "READ_AUTOMOD")
            by_name = {row.get("name"): row for row in existing}
            for name, spec in TARGET_RULES.items():
                actions = [{"type": 1, "metadata": {"custom_message": "Blocked by JABBAZI server safety."}}]
                if bot_log.isdigit():
                    actions.append({"type": 2, "metadata": {"channel_id": bot_log}})
                payload = {
                    "name": name,
                    **spec,
                    "actions": actions,
                    "enabled": True,
                    "exempt_roles": staff_ids,
                    "exempt_channels": [],
                }
                current = by_name.get(name)
                try:
                    if current:
                        changed = checked(
                            http, "PATCH",
                            f"/guilds/{guild}/auto-moderation/rules/{current['id']}",
                            "UPDATE_AUTOMOD", json=payload,
                        )
                    else:
                        changed = checked(
                            http, "POST", f"/guilds/{guild}/auto-moderation/rules",
                            "CREATE_AUTOMOD", json=payload,
                        )
                    result["automod"].append({
                        "name": name,
                        "id": str(changed.get("id", "")),
                        "enabled": bool(changed.get("enabled")),
                        "status": "VERIFIED" if changed.get("name") == name and changed.get("enabled") else "MISMATCH",
                    })
                except RuntimeError as exc:
                    result["automod"].append({"name": name, "status": "ACTION_REQUIRED"})
                    result["warnings"].append(str(exc))
        else:
            result["automod"].append({"status": "ACTION_REQUIRED_MANAGE_SERVER_PERMISSION"})

        if result["community"] == "ENABLED":
            response = request(http, "GET", f"/guilds/{guild}/onboarding", "READ_ONBOARDING")
            if response.status_code == 200:
                data = response.json()
                result["onboarding"] = "ENABLED" if data.get("enabled") else "AVAILABLE_NOT_ENABLED"
                result["onboarding_default_channels"] = len(data.get("default_channel_ids") or [])
                result["onboarding_prompts"] = len(data.get("prompts") or [])
            elif response.status_code in {403, 404}:
                result["onboarding"] = "OWNER_UI_REQUIRED"
            else:
                result["onboarding"] = "ACTION_REQUIRED"
                result["warnings"].append(f"READ_ONBOARDING_HTTP_{response.status_code}")
        else:
            result["onboarding"] = "COMMUNITY_REQUIRED"

    failures = [r for r in result["automod"] if r.get("status") not in {"VERIFIED"}]
    result["status"] = "VERIFIED" if not failures else "PARTIAL"
    return result


def main():
    try:
        result = configure()
        print("JABBAZI_NATIVE_SAFETY " + json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result["status"] == "VERIFIED" else 1
    except Exception as exc:
        print("JABBAZI_NATIVE_SAFETY " + json.dumps({"status": "UNAVAILABLE", "error": str(exc)[:120]}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

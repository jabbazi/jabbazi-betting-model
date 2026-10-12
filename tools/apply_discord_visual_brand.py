"""Apply the JABBAZI visual identity to the live Discord guild.

Each visual element is applied and verified independently so an unavailable guild
banner feature cannot block the icon, bot avatar, or role styling. Role IDs and
permissions are preserved. Third-party managed roles are untouched.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time

import httpx

API = "https://discord.com/api/v10"
PURPLE = 0x7F3DFF
ROYAL = 0x5B2EFF
VIOLET = 0x8A63FF
SILVER = 0xB9BCC6
MEMBER_GRAY = 0x90909A
ROOKIE_GRAY = 0x6B7280

ROLE_STYLE = {
    "JABBAZI": {"color": PURPLE, "hoist": True},
    "JABBAZI TEAM": {"color": ROYAL, "hoist": True},
    "MODERATOR": {"color": SILVER, "hoist": True},
    "INNER CIRCLE": {"color": VIOLET, "hoist": True},
    "JABBAZI VIP": {"color": PURPLE, "hoist": True},
    "SHARP": {"color": VIOLET, "hoist": False},
    "MEMBER": {"color": MEMBER_GRAY, "hoist": False},
    "ROOKIE": {"color": ROOKIE_GRAY, "hoist": False},
    "TRIAL VIP": {"color": ROOKIE_GRAY, "hoist": False},
}

def normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()

def data_uri(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    base64.b64decode(value, validate=True)
    return "data:image/jpeg;base64," + value

def request(http, method, path, operation, **kwargs):
    for attempt in range(4):
        response = http.request(method, path, **kwargs)
        if response.status_code != 429:
            break
        if attempt == 3:
            raise RuntimeError("RATE_LIMIT")
        try:
            delay = min(float(response.json().get("retry_after", 1)), 10)
        except Exception:
            delay = 1
        time.sleep(max(0.25, delay))
    if response.status_code >= 400:
        raise RuntimeError(f"{operation}_HTTP_{response.status_code}")
    return response.json() if response.content else None

def apply():
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    if not token or not guild.isdigit() or not owner.isdigit():
        raise RuntimeError("CONFIGURATION_MISSING")

    result = {
        "status": "APPLYING",
        "guild_icon": "SKIPPED",
        "guild_banner": "SKIPPED",
        "guild_banner_feature": False,
        "bot_avatar": "SKIPPED",
        "role_styles": [],
        "warnings": [],
    }
    headers = {
        "Authorization": "Bot " + token,
        "Content-Type": "application/json",
        "User-Agent": "JabbaziVisualBrand/1.1",
    }

    with httpx.Client(base_url=API, headers=headers, timeout=25) as http:
        info = request(http, "GET", f"/guilds/{guild}", "READ_GUILD")
        if str(info.get("owner_id")) != owner:
            raise RuntimeError("OWNER_MISMATCH")

        features = set(info.get("features") or [])
        result["guild_banner_feature"] = "BANNER" in features

        # Apply each binary asset independently.
        raw_icon = os.getenv("JABBAZI_VISUAL_ICON_B64", "").strip()
        if raw_icon:
            try:
                changed = request(
                    http, "PATCH", f"/guilds/{guild}", "PATCH_ICON",
                    json={"icon": data_uri(raw_icon)},
                )
                result["guild_icon"] = "VERIFIED" if changed.get("icon") else "MISMATCH"
            except Exception as exc:
                result["guild_icon"] = "ACTION_REQUIRED"
                result["warnings"].append("ICON_" + str(exc)[:80])

        raw_banner = os.getenv("JABBAZI_VISUAL_BANNER_B64", "").strip()
        if raw_banner:
            if "BANNER" not in features:
                result["guild_banner"] = "SERVER_FEATURE_UNAVAILABLE"
            else:
                try:
                    changed = request(
                        http, "PATCH", f"/guilds/{guild}", "PATCH_BANNER",
                        json={"banner": data_uri(raw_banner)},
                    )
                    result["guild_banner"] = "VERIFIED" if changed.get("banner") else "MISMATCH"
                except Exception as exc:
                    result["guild_banner"] = "ACTION_REQUIRED"
                    result["warnings"].append("BANNER_" + str(exc)[:80])

        raw_avatar = os.getenv("JABBAZI_VISUAL_BOT_AVATAR_B64", "").strip()
        if raw_avatar:
            try:
                changed_user = request(
                    http, "PATCH", "/users/@me", "PATCH_BOT_AVATAR",
                    json={"avatar": data_uri(raw_avatar)},
                )
                result["bot_avatar"] = "VERIFIED" if changed_user.get("avatar") else "MISMATCH"
            except Exception as exc:
                result["bot_avatar"] = "ACTION_REQUIRED"
                result["warnings"].append("AVATAR_" + str(exc)[:80])

        roles = request(http, "GET", f"/guilds/{guild}/roles", "READ_ROLES")
        me = request(http, "GET", "/users/@me", "READ_BOT")
        membership = request(
            http, "GET", f"/guilds/{guild}/members/{me['id']}", "READ_BOT_MEMBER"
        )
        bot_role_ids = {str(v) for v in membership.get("roles", [])}
        bot_top = max(
            (int(r.get("position", 0)) for r in roles if str(r["id"]) in bot_role_ids),
            default=0,
        )

        for role in roles:
            if role.get("managed"):
                continue
            style = ROLE_STYLE.get(normalize(role.get("name")))
            if not style:
                continue
            rid = str(role["id"])
            before_permissions = str(role.get("permissions", "0"))
            if int(role.get("position", 0)) >= bot_top:
                result["warnings"].append(f"ROLE_HIERARCHY_BLOCKED:{rid}")
                continue
            try:
                changed = request(
                    http, "PATCH", f"/guilds/{guild}/roles/{rid}", "STYLE_ROLE",
                    json={"color": style["color"], "hoist": style["hoist"]},
                )
                if (
                    str(changed.get("id")) != rid
                    or str(changed.get("permissions", "0")) != before_permissions
                ):
                    raise RuntimeError("ROLE_INVARIANT_FAILED")
                result["role_styles"].append({
                    "id": rid,
                    "name": changed.get("name"),
                    "color": changed.get("color"),
                    "hoist": changed.get("hoist"),
                    "status": "VERIFIED",
                })
            except Exception as exc:
                result["warnings"].append(f"ROLE_{rid}_" + str(exc)[:80])

        final_guild = request(http, "GET", f"/guilds/{guild}", "VERIFY_GUILD")
        final_user = request(http, "GET", "/users/@me", "VERIFY_BOT")
        if result["guild_icon"] == "VERIFIED" and not final_guild.get("icon"):
            result["guild_icon"] = "MISMATCH"
        if result["guild_banner"] == "VERIFIED" and not final_guild.get("banner"):
            result["guild_banner"] = "MISMATCH"
        if result["bot_avatar"] == "VERIFIED" and not final_user.get("avatar"):
            result["bot_avatar"] = "MISMATCH"

    bad = {"MISMATCH", "ACTION_REQUIRED"}
    result["status"] = "VERIFIED" if not (
        result["guild_icon"] in bad
        or result["guild_banner"] in bad
        or result["bot_avatar"] in bad
    ) else "PARTIAL"
    return result

def main():
    try:
        result = apply()
        print("JABBAZI_VISUAL_BRAND " + json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result["status"] == "VERIFIED" else 1
    except Exception as exc:
        print(
            "JABBAZI_VISUAL_BRAND "
            + json.dumps({"status": "UNAVAILABLE", "error": str(exc)[:120]}),
            flush=True,
        )
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

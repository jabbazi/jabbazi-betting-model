"""Apply the JABBAZI visual identity to the live Discord guild.

One-shot and verification-first. Binary env assets are optional; when absent or
invalid, a hot-pink JABBAZI fallback is generated deterministically in-process.
Role IDs and permissions are preserved. Third-party managed roles are untouched.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time

import httpx
from PIL import Image, ImageDraw, ImageFont

API = "https://discord.com/api/v10"
HOT_PINK = 0xFF0A8A
NEON_PINK = 0xFF1493
MAGENTA = 0xD90068
PINK_LIGHT = 0xFF4DB8
SILVER = 0xD9D9D9
MEMBER_GRAY = 0x90909A
ROOKIE_GRAY = 0x6B7280

ROLE_STYLE = {
    "JABBAZI": {"color": HOT_PINK, "hoist": True},
    "JABBAZI TEAM": {"color": MAGENTA, "hoist": True},
    "MODERATOR": {"color": SILVER, "hoist": True},
    "INNER CIRCLE": {"color": NEON_PINK, "hoist": True},
    "JABBAZI VIP": {"color": HOT_PINK, "hoist": True},
    "SHARP": {"color": PINK_LIGHT, "hoist": False},
    "MEMBER": {"color": MEMBER_GRAY, "hoist": False},
    "ROOKIE": {"color": ROOKIE_GRAY, "hoist": False},
    "TRIAL VIP": {"color": ROOKIE_GRAY, "hoist": False},
}

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def encoded_image(img: Image.Image, fmt="PNG", quality=90) -> str:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, fmt, quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, fmt, optimize=True)
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def env_image(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    try:
        base64.b64decode(value, validate=True)
    except Exception:
        return None
    return "data:image/jpeg;base64," + value


def crown(draw, cx, top, width, height):
    x0 = cx - width // 2
    x1 = cx + width // 2
    base_y = top + height
    points = [
        (x0, base_y - int(height * 0.24)),
        (x0 + int(width * 0.12), top + int(height * 0.36)),
        (x0 + int(width * 0.29), base_y - int(height * 0.42)),
        (cx, top),
        (x1 - int(width * 0.29), base_y - int(height * 0.42)),
        (x1 - int(width * 0.12), top + int(height * 0.36)),
        (x1, base_y - int(height * 0.24)),
        (x1 - int(width * 0.08), base_y),
        (x0 + int(width * 0.08), base_y),
    ]
    draw.polygon(points, fill=(255, 255, 255), outline=(255, 10, 138), width=max(3, width // 80))
    draw.line([(x0 + int(width * 0.08), base_y), (x1 - int(width * 0.08), base_y)], fill=(255, 20, 147), width=max(5, width // 50))


def generated_icon():
    """Discord-safe hot-pink J mark; avoids wide wordmark legibility loss."""
    img = Image.new("RGB", (512, 512), (9, 9, 9))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((18, 18, 494, 494), radius=88, outline=(255, 10, 138), width=8)
    font = ImageFont.truetype(FONT_BOLD, 260)
    box = draw.textbbox((0, 0), "J", font=font)
    x = (512 - (box[2] - box[0])) // 2
    draw.text((x + 6, 104), "J", font=font, fill=(217, 0, 104))
    draw.text((x, 98), "J", font=font, fill=(255, 255, 255))
    draw.arc((82, 275, 435, 460), start=12, end=346, fill=(255, 20, 147), width=18)
    draw.arc((110, 300, 420, 475), start=15, end=330, fill=(255, 10, 138), width=8)
    return encoded_image(img, "JPEG", 90)

def generated_avatar():
    return generated_icon()


def generated_banner():
    img = Image.new("RGB", (960, 540), (9, 9, 9))
    draw = ImageDraw.Draw(img)
    for i in range(0, 960, 48):
        draw.line((i, 0, i - 300, 540), fill=(13, 10, 24), width=2)
    crown(draw, 480, 58, 230, 132)
    font = ImageFont.truetype(FONT_BOLD, 112)
    small = ImageFont.truetype(FONT_REG, 27)
    word = "JABBAZI"
    box = draw.textbbox((0, 0), word, font=font)
    x = (960 - (box[2] - box[0])) // 2
    draw.text((x + 4, 216), word, font=font, fill=(255, 20, 147))
    draw.text((x, 210), word, font=font, fill=(236, 237, 242))
    sub = "SPORTS RESEARCH  •  DATA  •  DISCIPLINE  •  RESULTS"
    box2 = draw.textbbox((0, 0), sub, font=small)
    x2 = (960 - (box2[2] - box2[0])) // 2
    draw.text((x2, 365), sub, font=small, fill=(185, 188, 198))
    draw.line((190, 416, 770, 416), fill=(255, 10, 138), width=5)
    return encoded_image(img, "JPEG", 88)


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

    icon = env_image(os.getenv("JABBAZI_VISUAL_ICON_B64", "")) or generated_icon()
    banner = env_image(os.getenv("JABBAZI_VISUAL_BANNER_B64", "")) or generated_banner()
    avatar = env_image(os.getenv("JABBAZI_VISUAL_BOT_AVATAR_B64", "")) or generated_avatar()

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
        "User-Agent": "JabbaziVisualBrand/2.0",
    }

    with httpx.Client(base_url=API, headers=headers, timeout=25) as http:
        info = request(http, "GET", f"/guilds/{guild}", "READ_GUILD")
        if str(info.get("owner_id")) != owner:
            raise RuntimeError("OWNER_MISMATCH")

        features = set(info.get("features") or [])
        result["guild_banner_feature"] = "BANNER" in features

        try:
            changed = request(http, "PATCH", f"/guilds/{guild}", "PATCH_ICON", json={"icon": icon})
            result["guild_icon"] = "VERIFIED" if changed.get("icon") else "MISMATCH"
        except Exception as exc:
            result["guild_icon"] = "ACTION_REQUIRED"
            result["warnings"].append("ICON_" + str(exc)[:80])

        if "BANNER" not in features:
            result["guild_banner"] = "SERVER_FEATURE_UNAVAILABLE"
        else:
            try:
                changed = request(http, "PATCH", f"/guilds/{guild}", "PATCH_BANNER", json={"banner": banner})
                result["guild_banner"] = "VERIFIED" if changed.get("banner") else "MISMATCH"
            except Exception as exc:
                result["guild_banner"] = "ACTION_REQUIRED"
                result["warnings"].append("BANNER_" + str(exc)[:80])

        try:
            changed_user = request(http, "PATCH", "/users/@me", "PATCH_BOT_AVATAR", json={"avatar": avatar})
            result["bot_avatar"] = "VERIFIED" if changed_user.get("avatar") else "MISMATCH"
        except Exception as exc:
            result["bot_avatar"] = "ACTION_REQUIRED"
            result["warnings"].append("AVATAR_" + str(exc)[:80])

        roles = request(http, "GET", f"/guilds/{guild}/roles", "READ_ROLES")
        me = request(http, "GET", "/users/@me", "READ_BOT")
        membership = request(http, "GET", f"/guilds/{guild}/members/{me['id']}", "READ_BOT_MEMBER")
        bot_role_ids = {str(v) for v in membership.get("roles", [])}
        bot_top = max((int(r.get("position", 0)) for r in roles if str(r["id"]) in bot_role_ids), default=0)

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
                if str(changed.get("id")) != rid or str(changed.get("permissions", "0")) != before_permissions:
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
        print("JABBAZI_VISUAL_BRAND " + json.dumps({"status": "UNAVAILABLE", "error": str(exc)[:120]}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

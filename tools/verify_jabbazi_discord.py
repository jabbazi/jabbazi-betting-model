"""Read-only final verification for the live JABBAZI Discord."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from jabazi.discord_access import is_staff_name, vip_role_ids
from jabazi.discord_migration import (
    ADMIN,
    POSTING,
    VIEW,
    channel_name,
    configured_vip_ids,
    effective_permissions,
    request,
)
from jabazi.discord_onboarding import is_introduction, read_pins

API = "https://discord.com/api/v10"


def main():
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    if not token or not guild.isdigit() or not owner.isdigit():
        raise SystemExit("Discord verification configuration missing")

    bp = json.loads(Path("docs/discord/server_blueprint.json").read_text())
    seed = json.loads(Path("docs/discord/seed_content.json").read_text())
    headers = {"Authorization": "Bot " + token, "User-Agent": "JabbaziVerify/1.0"}

    failures = []
    warnings = []
    verified_pins = []
    channel_ids = {}

    with httpx.Client(base_url=API, headers=headers, timeout=20.0) as http:
        info = request(http, "GET", f"/guilds/{guild}", "VERIFY_GUILD")
        bot = request(http, "GET", "/users/@me", "VERIFY_BOT")
        bot_id = str(bot["id"])
        bot_member = request(
            http, "GET", f"/guilds/{guild}/members/{bot_id}", "VERIFY_BOT_MEMBER"
        )
        owner_member = request(
            http, "GET", f"/guilds/{guild}/members/{owner}", "VERIFY_OWNER_MEMBER"
        )
        roles = request(http, "GET", f"/guilds/{guild}/roles", "VERIFY_ROLES")
        channels = request(http, "GET", f"/guilds/{guild}/channels", "VERIFY_CHANNELS")
        application = request(http, "GET", "/oauth2/applications/@me", "VERIFY_APP")
        commands = request(
            http,
            "GET",
            f"/applications/{application['id']}/guilds/{guild}/commands",
            "VERIFY_COMMANDS",
        )

        if info.get("name") != "JABBAZI 👑":
            failures.append("SERVER_NAME")
        if bot_member.get("nick") != "JABBAZI SYSTEM":
            failures.append("BOT_NICKNAME")

        owner_roles = {str(x) for x in owner_member.get("roles", [])}
        founder = next(
            (
                r
                for r in roles
                if not r.get("managed")
                and channel_name(r.get("name", "")).replace(" ", "-") == "jabbazi"
            ),
            None,
        )
        # Emoji role names are not channel names; normalized suffix check is safer.
        if founder is None:
            founder = next(
                (
                    r for r in roles
                    if not r.get("managed")
                    and "JABBAZI" == "".join(
                        ch if ch.isalnum() else " " for ch in r.get("name", "")
                    ).strip().upper()
                ),
                None,
            )
        if founder is None or str(founder["id"]) not in owner_roles:
            failures.append("FOUNDER_ROLE")

        categories = [c for c in channels if c.get("type") == 4]
        category_by_name = {}
        for spec in bp["categories"]:
            matches = [c for c in categories if c.get("name") == spec["name"]]
            if len(matches) != 1:
                failures.append("CATEGORY:" + spec["name"])
                continue
            category_by_name[spec["name"]] = matches[0]

        active_names = [spec["name"] for spec in bp["categories"]]
        ordered = [
            c["name"]
            for c in sorted(categories, key=lambda row: row.get("position", 0))
            if c["name"] in active_names
        ]
        if ordered != active_names:
            failures.append("CATEGORY_ORDER")

        vip = vip_role_ids(roles, configured_vip_ids())
        if not vip:
            failures.append("VIP_ROLE_SET")
        staff = {str(r["id"]) for r in roles if is_staff_name(r.get("name"))}

        display = bp.get("channel_display_names", {})
        read_only = set(bp.get("read_only_channels", []))
        active_channel_rows = []

        for category in bp["categories"]:
            parent = category_by_name.get(category["name"])
            if parent is None:
                continue
            for key in category["channels"]:
                expected_name = display.get(key, key)
                matches = [
                    c
                    for c in channels
                    if c.get("type") == 0
                    and c.get("name") == expected_name
                    and str(c.get("parent_id")) == str(parent["id"])
                ]
                if len(matches) != 1:
                    failures.append("CHANNEL:" + key)
                    continue
                row = matches[0]
                channel_ids[key] = str(row["id"])
                active_channel_rows.append((key, row, category["access"]))
                expected_topic = bp.get("channel_topics", {}).get(key, "")
                if row.get("topic", "") != expected_topic:
                    failures.append("TOPIC:" + key)

                free_visible = bool(
                    effective_permissions(guild, "free-sim", [], roles, row, owner) & VIEW
                )
                if free_visible != (category["access"] == "public"):
                    failures.append("FREE_ACCESS:" + key)

                for rid in vip:
                    vp = effective_permissions(
                        guild, "vip-sim", [rid], roles, row, owner
                    )
                    if bool(vp & VIEW) != (category["access"] != "staff"):
                        failures.append("VIP_ACCESS:" + key)
                        break

                if key in read_only:
                    for assigned in ([], *[[rid] for rid in vip]):
                        perms = effective_permissions(
                            guild, "readonly-sim", assigned, roles, row, owner
                        )
                        if perms & POSTING:
                            failures.append("READ_ONLY:" + key)
                            break

                if key in seed:
                    try:
                        pins = read_pins(http, str(row["id"]))
                        guides = [
                            m
                            for m in pins
                            if str(m.get("author", {}).get("id")) == bot_id
                            and is_introduction(m)
                        ]
                        if len(guides) != 1:
                            failures.append("PIN:" + key)
                        else:
                            verified_pins.append(key)
                    except Exception:
                        failures.append("PIN_READ:" + key)

        if len(active_channel_rows) != sum(
            len(category["channels"]) for category in bp["categories"]
        ):
            failures.append("ACTIVE_CHANNEL_COUNT")

        names_and_topics = " ".join(
            [info.get("name", "")]
            + [c.get("name", "") + " " + (c.get("topic") or "") for _, c, _ in active_channel_rows]
        ).upper()
        if "JABBAZI GURU" in names_and_topics:
            failures.append("LEGACY_PUBLIC_BRAND")

        command_names = {c.get("name") for c in commands}
        required_commands = {"vip", "cheatsheet", "alerts", "support", "card", "performance"}
        if not required_commands.issubset(command_names):
            failures.append("COMMANDS")

        for old in channels:
            if old.get("type") != 0 or channel_name(old.get("name", "")) != "owner-archive":
                continue
            for rid in vip | staff:
                perms = effective_permissions(
                    guild, "archive-sim", [rid], roles, old, owner
                )
                if not perms & ADMIN and perms & VIEW:
                    failures.append("OWNER_ARCHIVE_EXPOSED")
                    break

        result = {
            "status": "VERIFIED" if not failures else "ACTION_REQUIRED",
            "guild_name": info.get("name"),
            "bot_nickname": bot_member.get("nick"),
            "active_categories": len(category_by_name),
            "active_channels": len(active_channel_rows),
            "verified_pins": len(verified_pins),
            "expected_pins": len(seed),
            "vip_roles": len(vip),
            "staff_roles": len(staff),
            "commands": sorted(command_names & required_commands),
            "channel_ids": channel_ids,
            "warnings": warnings,
            "failures": sorted(set(failures)),
        }
        print(
            "JABBAZI_FINAL_VERIFICATION "
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )
        return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

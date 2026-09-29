"""Repair and compact the live JABBAZI Discord safely.

Dry-run by default. --apply creates/moves only managed JABBAZI objects and repairs
permissions on BOTH existing and new channels. --archive-obsolete moves superseded
JABBAZI channels into a hidden staff archive instead of deleting history.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

VIEW = 1 << 10
SEND = 1 << 11
READ_HISTORY = 1 << 16
API = "https://discord.com/api/v10"

MANAGED_CATEGORIES = {
    "━━ START HERE ━━",
    "━━ ANNOUNCEMENTS ━━",
    "━━ DAILY JABBAZI ━━",
    "━━ VIP PICKS ━━",
    "━━ SPORT RESEARCH ━━",
    "━━ CHEAT SHEETS ━━",
    "━━ JABBAZI RESEARCH ━━",
    "━━ LEARN HOW TO ━━",
    "━━ COMMUNITY ━━",
    "━━ RESULTS / TRANSPARENCY ━━",
    "━━ MEMBER SUPPORT ━━",
    "━━ STAFF ONLY ━━",
    "━━ JABBAZI VIP ━━",
    "━━ SUPPORT ━━",
}


def load_blueprint():
    return json.loads(Path("docs/discord/server_blueprint.json").read_text())


def resolve_role(roles, *, env_name, fallback_name):
    configured = os.getenv(env_name, "").strip()
    if configured:
        matches = [r for r in roles if str(r["id"]) == configured]
        if len(matches) != 1:
            raise SystemExit(f"{env_name} does not match a role in this guild")
        return matches[0]
    matches = [r for r in roles if r["name"] == fallback_name]
    if not matches:
        raise SystemExit(
            f"No {fallback_name!r} role exists; set {env_name} to the intended role ID"
        )
    # Duplicate legacy names are tolerated; configured ID remains authoritative.
    return matches[0]


def put_overwrite(http, channel_id, target_id, target_type, allow, deny):
    http.put(
        f"/channels/{channel_id}/permissions/{target_id}",
        json={"type": target_type, "allow": str(allow), "deny": str(deny)},
    ).raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive-obsolete", action="store_true")
    args = parser.parse_args()

    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "")
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "")
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "")
    if not token or not guild.isdigit() or not owner.isdigit():
        raise SystemExit("Discord token, guild ID and owner ID are required")

    bp = load_blueprint()
    headers = {"Authorization": "Bot " + token, "User-Agent": "JABBAZI-GURU/1.1"}
    with httpx.Client(base_url=API, headers=headers, timeout=20) as http:
        info = http.get(f"/guilds/{guild}").raise_for_status().json()
        if str(info["owner_id"]) != owner:
            raise SystemExit("Configured Discord owner does not own target guild")

        roles_list = http.get(f"/guilds/{guild}/roles").raise_for_status().json()
        roles = {r["name"]: r for r in roles_list}
        configured_vip = os.getenv("JABBAZI_DISCORD_VIP_ROLE_ID", "").strip()
        if configured_vip:
            vip = resolve_role(
                roles_list, env_name="JABBAZI_DISCORD_VIP_ROLE_ID", fallback_name="VIP"
            )
        else:
            vip_candidates = [
                r for r in roles_list
                if "VIP" in str(r.get("name") or "").strip().upper()
            ]
            if not vip_candidates:
                raise SystemExit("No VIP-family role exists in this guild")
            vip = next((r for r in vip_candidates if r["name"] == "VIP"), vip_candidates[0])
        plan = {
            "vip_role_id": str(vip["id"]),
            "create_roles": [],
            "create_categories": [],
            "create_channels": [],
            "move_channels": [],
            "repair_permissions": [],
            "archive_channels": [],
            "warnings": [],
        }

        for spec in bp["roles"]:
            if spec["name"] not in roles:
                plan["create_roles"].append(spec["name"])
                if args.apply:
                    roles[spec["name"]] = http.post(
                        f"/guilds/{guild}/roles",
                        json={
                            "name": spec["name"],
                            "color": spec["color"],
                            "hoist": spec["hoist"],
                            "mentionable": False,
                            "permissions": "0",
                        },
                    ).raise_for_status().json()

        channels = http.get(f"/guilds/{guild}/channels").raise_for_status().json()
        by_key = {(c["name"], c["type"]): c for c in channels}

        def desired_overwrites(access):
            if access == "public":
                return [(guild, 0, VIEW | READ_HISTORY, 0)]
            if access == "vip":
                result = [
                    (guild, 0, 0, VIEW),
                    (owner, 1, VIEW | SEND | READ_HISTORY, 0),
                ]
                for role in roles.values():
                    if "VIP" in str(role.get("name") or "").strip().upper():
                        result.append(
                            (str(role["id"]), 0, VIEW | SEND | READ_HISTORY, 0)
                        )
                return result
            result = [(guild, 0, 0, VIEW), (owner, 1, VIEW | SEND | READ_HISTORY, 0)]
            for name in ("JABBAZI TEAM", "MODERATOR"):
                if name in roles:
                    result.append((str(roles[name]["id"]), 0, VIEW | SEND | READ_HISTORY, 0))
            return result

        def repair(channel, access):
            plan["repair_permissions"].append(
                {"channel": channel["name"], "id": str(channel["id"]), "access": access}
            )
            if not args.apply:
                return
            for target, target_type, allow, deny in desired_overwrites(access):
                put_overwrite(http, channel["id"], target, target_type, allow, deny)

        desired_channel_names = set()

        for category in bp["categories"]:
            parent = by_key.get((category["name"], 4))
            if parent is None:
                plan["create_categories"].append(category["name"])
                if args.apply:
                    parent = http.post(
                        f"/guilds/{guild}/channels",
                        json={"name": category["name"], "type": 4},
                    ).raise_for_status().json()
                    by_key[(category["name"], 4)] = parent
            if parent is not None:
                repair(parent, category["access"])

            for name in category["channels"]:
                desired_channel_names.add(name)
                channel = by_key.get((name, 0))
                if channel is None:
                    plan["create_channels"].append(name)
                    if args.apply:
                        channel = http.post(
                            f"/guilds/{guild}/channels",
                            json={
                                "name": name,
                                "type": 0,
                                "parent_id": parent["id"],
                                "rate_limit_per_user": 5
                                if name in {"general", "sports-talk"}
                                else 0,
                            },
                        ).raise_for_status().json()
                        by_key[(name, 0)] = channel
                elif parent is not None and str(channel.get("parent_id")) != str(parent["id"]):
                    plan["move_channels"].append(
                        {"channel": name, "to_category": category["name"]}
                    )
                    if args.apply:
                        channel = http.patch(
                            f"/channels/{channel['id']}",
                            json={"parent_id": parent["id"]},
                        ).raise_for_status().json()
                        by_key[(name, 0)] = channel
                if channel is not None:
                    repair(channel, category["access"])
                    if category["access"] == "vip":
                        for overwrite in channel.get("permission_overwrites", []):
                            if (
                                overwrite.get("type") == 1
                                and int(overwrite.get("deny", "0")) & VIEW
                                and str(overwrite.get("id")) != owner
                            ):
                                plan["warnings"].append(
                                    f"{name}: member-specific View Channel deny may override VIP"
                                )

        if args.archive_obsolete:
            archive = by_key.get(("━━ ARCHIVE ━━", 4))
            if archive is None:
                plan["create_categories"].append("━━ ARCHIVE ━━")
                if args.apply:
                    archive = http.post(
                        f"/guilds/{guild}/channels",
                        json={"name": "━━ ARCHIVE ━━", "type": 4},
                    ).raise_for_status().json()
                    by_key[("━━ ARCHIVE ━━", 4)] = archive
            if archive is not None:
                repair(archive, "staff")

            managed_parent_ids = {
                str(c["id"])
                for c in channels
                if c["type"] == 4 and c["name"] in MANAGED_CATEGORIES
            }
            for channel in channels:
                if (
                    channel["type"] == 0
                    and channel["name"] not in desired_channel_names
                    and str(channel.get("parent_id")) in managed_parent_ids
                ):
                    plan["archive_channels"].append(channel["name"])
                    if args.apply:
                        http.patch(
                            f"/channels/{channel['id']}",
                            json={"parent_id": archive["id"]},
                        ).raise_for_status()
                        repair(channel, "staff")

        try:
            automod = http.get(
                f"/guilds/{guild}/auto-moderation/rules"
            ).raise_for_status().json()
        except httpx.HTTPStatusError:
            automod = []
        if not any(rule.get("name") == "JABBAZI Mention Spam" for rule in automod):
            plan["automod"] = ["JABBAZI Mention Spam"]
            if args.apply:
                http.post(
                    f"/guilds/{guild}/auto-moderation/rules",
                    json={
                        "name": "JABBAZI Mention Spam",
                        "event_type": 1,
                        "trigger_type": 5,
                        "trigger_metadata": {
                            "mention_total_limit": 5,
                            "mention_raid_protection_enabled": True,
                        },
                        "actions": [
                            {"type": 1, "metadata": {"custom_message": "Please avoid mass mentions."}}
                        ],
                        "enabled": True,
                        "exempt_roles": [],
                        "exempt_channels": [],
                    },
                ).raise_for_status()
        else:
            plan["automod"] = []

        print(
            json.dumps(
                {
                    "mode": "APPLIED" if args.apply else "DRY_RUN",
                    "guild_id": guild,
                    "plan": plan,
                    "note": (
                        "Existing managed channels are repaired. Obsolete channels are "
                        "archived, never deleted, only when --archive-obsolete is supplied."
                    ),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

"""Targeted repair for the active JABBAZI welcome channel only."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from jabazi.discord_access import is_staff_name, vip_role_ids
from jabazi.discord_migration import configured_vip_ids, overwrites, request
from jabazi.discord_onboarding import seed
from jabazi.persistence.store import Store

API = "https://discord.com/api/v10"
CATEGORY = "👑 WELCOME TO JABBAZI"
KEY = "welcome"


def main():
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    db = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "").strip()
    if not token or not guild.isdigit() or not owner.isdigit() or not db:
        raise SystemExit("Welcome repair configuration missing")

    bp = json.loads(Path("docs/discord/server_blueprint.json").read_text())
    expected_name = bp["channel_display_names"][KEY]
    expected_topic = bp["channel_topics"][KEY]

    headers = {"Authorization": "Bot " + token, "User-Agent": "JabbaziWelcomeRepair/1.0"}
    store = Store(db)
    try:
        if not store.ready():
            raise RuntimeError("WELCOME_REPAIR_DATABASE_NOT_READY")
        with httpx.Client(base_url=API, headers=headers, timeout=20.0) as http:
            info = request(http, "GET", f"/guilds/{guild}", "WELCOME_READ_GUILD")
            if str(info.get("owner_id")) != owner:
                raise RuntimeError("WELCOME_REPAIR_OWNER_MISMATCH")
            bot = str(request(http, "GET", "/users/@me", "WELCOME_READ_BOT")["id"])
            roles = request(http, "GET", f"/guilds/{guild}/roles", "WELCOME_READ_ROLES")
            channels = request(
                http, "GET", f"/guilds/{guild}/channels", "WELCOME_READ_CHANNELS"
            )
            print("JABBAZI_WELCOME_REPAIR STAGE_READ_LIVE_STATE", flush=True)
            parents = [c for c in channels if c.get("type") == 4 and c.get("name") == CATEGORY]
            print(
                "JABBAZI_WELCOME_REPAIR "
                + json.dumps({"status": "STAGE", "stage": "CATEGORY_READ", "matches": len(parents)}),
                flush=True,
            )
            if len(parents) != 1:
                raise RuntimeError("WELCOME_REPAIR_CATEGORY_NOT_UNIQUE")
            parent = parents[0]

            matches = [
                c for c in channels
                if c.get("type") == 0
                and c.get("name") == expected_name
                and str(c.get("parent_id")) == str(parent["id"])
            ]
            created = False
            if len(matches) > 1:
                raise RuntimeError("WELCOME_REPAIR_DUPLICATE_ACTIVE_WELCOME")
            if matches:
                channel = matches[0]
            else:
                vip = vip_role_ids(roles, configured_vip_ids())
                staff = {str(r["id"]) for r in roles if is_staff_name(r.get("name"))}
                print(
                    "JABBAZI_WELCOME_REPAIR "
                    + json.dumps(
                        {
                            "status": "STAGE",
                            "stage": "PERMISSIONS_RESOLVED",
                            "vip_roles": len(vip),
                            "staff_roles": len(staff),
                        }
                    ),
                    flush=True,
                )
                payload = {
                    "name": expected_name,
                    "type": 0,
                    "parent_id": parent["id"],
                    "position": 0,
                    "permission_overwrites": overwrites(
                        "public",
                        guild=guild,
                        owner=owner,
                        bot=bot,
                        vip=vip,
                        staff=staff,
                        read_only=True,
                    ),
                    "topic": expected_topic,
                    "rate_limit_per_user": 0,
                }
                print("JABBAZI_WELCOME_REPAIR STAGE_CREATE_CHANNEL", flush=True)
                print(
                    "JABBAZI_WELCOME_REPAIR "
                    + json.dumps({"status": "STAGE", "stage": "CREATE_REQUEST"}),
                    flush=True,
                )
                channel = request(
                    http,
                    "POST",
                    f"/guilds/{guild}/channels",
                    "WELCOME_CREATE_CHANNEL",
                    json=payload,
                )
                created = True

            if channel.get("name") != expected_name:
                raise RuntimeError("WELCOME_REPAIR_NAME_VERIFY_FAILED")
            if str(channel.get("parent_id")) != str(parent["id"]):
                raise RuntimeError("WELCOME_REPAIR_PARENT_VERIFY_FAILED")
            if (channel.get("topic") or "") != expected_topic:
                print("JABBAZI_WELCOME_REPAIR STAGE_UPDATE_TOPIC", flush=True)
                channel = request(
                    http,
                    "PATCH",
                    f"/channels/{channel['id']}",
                    "WELCOME_UPDATE_TOPIC",
                    json={"topic": expected_topic},
                )
            if (channel.get("topic") or "") != expected_topic:
                raise RuntimeError("WELCOME_REPAIR_TOPIC_VERIFY_FAILED")

            print("JABBAZI_WELCOME_REPAIR STAGE_SEED_AND_PIN", flush=True)
            onboarding = seed(http, store, guild=guild, owner=owner, apply=True)
            row = next(
                (r for r in onboarding["plan"] if r.get("channel") == KEY),
                None,
            )
            if not row or row.get("status") != "PINNED":
                raise RuntimeError("WELCOME_REPAIR_PIN_VERIFY_FAILED")

            result = {
                "status": "VERIFIED",
                "created": created,
                "channel_id": str(channel["id"]),
                "name": channel["name"],
                "pinned_message_id": str(row["message_id"]),
            }
            print(
                "JABBAZI_WELCOME_REPAIR "
                + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                flush=True,
            )
            return 0
    finally:
        store.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(
            "JABBAZI_WELCOME_REPAIR "
            + json.dumps(
                {
                    "status": "ACTION_REQUIRED",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )
        raise SystemExit(1)

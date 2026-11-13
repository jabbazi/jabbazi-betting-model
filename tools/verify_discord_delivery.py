"""Verify an explicitly approved PRIVATE Discord test target, without migrations.

Read-only by default. Sending requires both --send-test and the separate
JABBAZI_DISCORD_TEST_SEND_APPROVED=true environment gate.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import httpx

from jabazi.discord_migration import VIEW, SEND, effective_permissions


def validate_private_test_target(guild_id, owner_id, bot_id, member_roles, roles, channel):
    """Refuse wrong guild, public visibility, missing bot send, or non-text target."""
    if str(channel.get("guild_id")) != str(guild_id) or channel.get("type") != 0:
        return "WRONG_GUILD_OR_CHANNEL_TYPE"
    public = [
        p for p in channel.get("permission_overwrites", [])
        if str(p.get("id")) == str(guild_id) and p.get("type") == 0
    ]
    if len(public) != 1 or not int(public[0].get("deny", 0)) & VIEW:
        return "NOT_EXPLICITLY_PRIVATE"
    everyone = effective_permissions(guild_id, "__non_member__", (), roles, channel, owner_id)
    if everyone & VIEW:
        return "PUBLIC_VISIBILITY"
    permissions = effective_permissions(
        guild_id, bot_id, member_roles, roles, channel, owner_id
    )
    if permissions & (VIEW | SEND) != VIEW | SEND:
        return "BOT_VIEW_SEND_NOT_GRANTED"
    return "VERIFIED_PRIVATE_TARGET"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Discord delivery preflight")
    parser.add_argument("--send-test", action="store_true", help="Send one marked private test message only with second environment approval")
    args = parser.parse_args(argv)

    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    test_channel = os.getenv("JABBAZI_DISCORD_DELIVERY_TEST_CHANNEL_ID", "").strip()
    if not token or not all(s.isdigit() for s in (guild, owner, test_channel)):
        print("DISCORD_DELIVERY_TEST " + json.dumps({"status": "CONFIGURATION_REQUIRED"}))
        return 2
    with httpx.Client(
        base_url="https://discord.com/api/v10",
        headers={"Authorization": "Bot " + token, "User-Agent": "JabbaziDeliveryTest/1"},
        timeout=20,
    ) as http:
        def fetch(path):
            response = http.get(path)
            if response.status_code != 200:
                raise RuntimeError("PREFLIGHT_HTTP_" + str(response.status_code))
            return response.json()

        try:
            bot = fetch("/users/@me")
            guild_doc = fetch("/guilds/" + guild)
            if str(guild_doc.get("owner_id")) != owner:
                raise RuntimeError("GUILD_OWNER_MISMATCH")
            member = fetch(f"/guilds/{guild}/members/{bot['id']}")
            roles = fetch("/guilds/" + guild + "/roles")
            channel = fetch("/channels/" + test_channel)
            status = validate_private_test_target(
                guild, owner, str(bot["id"]), member.get("roles", []), roles, channel,
            )
            if status != "VERIFIED_PRIVATE_TARGET":
                raise RuntimeError(status)

            if not args.send_test:
                print("DISCORD_DELIVERY_TEST " + json.dumps({
                    "status": "PRIVATE_TARGET_VERIFIED_NO_MESSAGE_SENT", "channel_id": test_channel,
                }, separators=(",", ":")))
                return 0
            if os.getenv("JABBAZI_DISCORD_TEST_SEND_APPROVED", "").lower() != "true":
                raise RuntimeError("EXPLICIT_SEND_APPROVAL_REQUIRED")

            payload = {
                "content": "👑 JABBAZI DELIVERY TEST — authorized private-channel diagnostic only. "
                           "No betting recommendation. No live cheat sheet was generated.",
                "allowed_mentions": {"parse": []},
            }
            response = http.post(f"/channels/{test_channel}/messages", json=payload)
            if response.status_code not in (200, 201):
                raise RuntimeError("SEND_HTTP_" + str(response.status_code))
            message_id = str(response.json().get("id") or "")
            if not message_id.isdigit():
                raise RuntimeError("DELIVERY_ACK_MISSING_MESSAGE_ID")
            print("DISCORD_DELIVERY_TEST " + json.dumps({
                "status": "DELIVERED", "channel_id": test_channel,
                "message_id": message_id, "at_utc": datetime.now(UTC).isoformat(),
            }, separators=(",", ":")))
            return 0
        except (RuntimeError, httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            label = str(exc)
            if not label.startswith((
                "PREFLIGHT_HTTP_", "SEND_HTTP_", "WRONG_GUILD_OR_CHANNEL_TYPE",
                "NOT_EXPLICITLY_PRIVATE", "PUBLIC_VISIBILITY",
                "BOT_VIEW_SEND_NOT_GRANTED", "GUILD_OWNER_MISMATCH",
                "EXPLICIT_SEND_APPROVAL_REQUIRED", "DELIVERY_ACK_MISSING_MESSAGE_ID"
            )):
                label = type(exc).__name__
            print("DISCORD_DELIVERY_TEST " + json.dumps({"status": "ACTION_REQUIRED", "reason": label}))
            return 1


if __name__ == "__main__":
    raise SystemExit(main())

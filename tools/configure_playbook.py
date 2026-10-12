"""One-shot least-privilege configuration for the Action Network Playbook Discord bot.

The script is safe by default. --apply changes only Playbook's Discord role/channel
permissions. --test performs a bot-authored mention test after permissions are verified.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import httpx

API = "https://discord.com/api/v10"

VIEW = 1 << 10
SEND = 1 << 11
EMBED = 1 << 14
ATTACH = 1 << 15
HISTORY = 1 << 16
ADMINISTRATOR = 1 << 3

TARGET_ALLOW = VIEW | SEND | EMBED | ATTACH | HISTORY

# Playbook belongs only in actual VIP pick/parlay channels.
TARGET_EXACT = {
    "jabbazi-picks",
    "daily-card",
    "vip-picks",
    "mlb-picks",
    "nfl-picks",
    "college-football-picks",
    "cfb-picks",
    "parlays-and-alternates",
    "parlays-sgps",
    "best-two-parlay",
}
TARGET_HINTS = ("pick", "parlay", "daily-card", "card")


def checked(response: httpx.Response, operation: str) -> httpx.Response:
    if response.status_code == 429:
        retry = float(response.json().get("retry_after", 1))
        if retry > 20:
            raise RuntimeError("PLAYBOOK_RATE_LIMIT_TOO_LONG")
        time.sleep(max(0.2, retry))
        return checked(response.request.send(), operation)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        raise RuntimeError(f"PLAYBOOK_{operation}_HTTP_{response.status_code}") from None
    return response


def request(http: httpx.Client, method: str, path: str, payload=None):
    response = http.request(method, path, json=payload)
    checked(response, method + "_" + path.rsplit("/", 1)[-1].upper())
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def target_channels(channels):
    categories = {str(c["id"]): c["name"] for c in channels if c.get("type") == 4}
    targets = []
    for channel in channels:
        if channel.get("type") not in (0, 5):
            continue
        name = channel.get("name", "").lower()
        parent = categories.get(str(channel.get("parent_id")), "")
        vip_parent = "vip" in parent.lower()
        if name in TARGET_EXACT or (
            vip_parent and any(hint in name for hint in TARGET_HINTS)
        ):
            # Deliberately exclude chat/research/status/boost channels unless they are
            # explicitly named above.
            if "chat" not in name and "research" not in name and "status" not in name:
                targets.append(channel)
    return targets, categories


def configure(*, apply: bool, test: bool):
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "").strip()
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "").strip()
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "").strip()
    if not token or not guild.isdigit() or not owner.isdigit():
        raise RuntimeError("PLAYBOOK_DISCORD_CONFIGURATION_MISSING")

    headers = {
        "Authorization": "Bot " + token,
        "Content-Type": "application/json",
        "User-Agent": "JabbaziPlaybookSetup/1.0",
    }
    with httpx.Client(base_url=API, headers=headers, timeout=20.0) as http:
        guild_info = request(http, "GET", f"/guilds/{guild}")
        if str(guild_info.get("owner_id")) != owner:
            raise RuntimeError("PLAYBOOK_OWNER_MISMATCH")

        roles = request(http, "GET", f"/guilds/{guild}/roles")
        matches = [
            r for r in roles
            if r.get("managed")
            and isinstance(r.get("tags"), dict)
            and r["tags"].get("bot_id")
            and "playbook" in r.get("name", "").lower()
        ]
        if len(matches) != 1:
            raise RuntimeError("PLAYBOOK_ROLE_NOT_UNIQUE")
        role = matches[0]
        playbook_user_id = str(role["tags"]["bot_id"])
        role_id = str(role["id"])
        current_role_permissions = int(role.get("permissions", "0"))
        if current_role_permissions & ADMINISTRATOR:
            # We remove this below in apply mode. In dry-run, report it explicitly.
            admin_present = True
        else:
            admin_present = False

        channels = request(http, "GET", f"/guilds/{guild}/channels")
        targets, categories = target_channels(channels)
        if not targets:
            raise RuntimeError("PLAYBOOK_NO_TARGET_CHANNELS")
        if len(targets) > 12:
            raise RuntimeError("PLAYBOOK_TARGET_SCOPE_TOO_BROAD")

        target_ids = {str(c["id"]) for c in targets}
        text_channels = [c for c in channels if c.get("type") in (0, 5)]

        plan = {
            "status": "PLAN" if not apply else "APPLYING",
            "playbook_role": role.get("name"),
            "playbook_user_id": playbook_user_id,
            "administrator_was_present": admin_present,
            "target_channels": [
                {
                    "id": str(c["id"]),
                    "name": c["name"],
                    "category": categories.get(str(c.get("parent_id")), ""),
                }
                for c in targets
            ],
            "denied_text_channels": len(text_channels) - len(targets),
            "minimum_permissions": [
                "View Channel",
                "Send Messages",
                "Read Message History",
                "Embed Links",
                "Attach Files",
            ],
        }
        if not apply:
            return plan

        # Zero the bot-managed role permissions. Target channels get the exact permissions
        # needed through explicit channel overwrites. This strips Administrator and other
        # unnecessary guild-wide privileges if the role had them.
        request(
            http,
            "PATCH",
            f"/guilds/{guild}/roles/{role_id}",
            {"permissions": "0"},
        )

        # Deny Playbook in every existing category by default so synced/new child channels
        # under those categories stay inaccessible unless explicitly allowed below.
        for category in [c for c in channels if c.get("type") == 4]:
            request(
                http,
                "PUT",
                f"/channels/{category['id']}/permissions/{role_id}",
                {"type": 0, "allow": "0", "deny": str(VIEW)},
            )

        # Explicitly deny every existing non-target text/announcement channel.
        for channel in text_channels:
            if str(channel["id"]) in target_ids:
                continue
            request(
                http,
                "PUT",
                f"/channels/{channel['id']}/permissions/{role_id}",
                {"type": 0, "allow": "0", "deny": str(VIEW)},
            )

        # Grant only the exact minimum on approved VIP pick/parlay channels.
        for channel in targets:
            request(
                http,
                "PUT",
                f"/channels/{channel['id']}/permissions/{role_id}",
                {"type": 0, "allow": str(TARGET_ALLOW), "deny": "0"},
            )

        # Read back the live overwrites and role permissions.
        live_roles = request(http, "GET", f"/guilds/{guild}/roles")
        live_role = next(r for r in live_roles if str(r["id"]) == role_id)
        if int(live_role.get("permissions", "0")) != 0:
            raise RuntimeError("PLAYBOOK_ROLE_PERMISSION_REDUCTION_FAILED")

        live_channels = request(http, "GET", f"/guilds/{guild}/channels")
        verified = {}
        for channel in [c for c in live_channels if c.get("type") in (0, 5)]:
            overwrite = next(
                (
                    p for p in channel.get("permission_overwrites", [])
                    if str(p.get("id")) == role_id and int(p.get("type", -1)) == 0
                ),
                None,
            )
            if str(channel["id"]) in target_ids:
                ok = bool(
                    overwrite
                    and int(overwrite.get("allow", "0")) & TARGET_ALLOW == TARGET_ALLOW
                    and int(overwrite.get("deny", "0")) & VIEW == 0
                )
            else:
                ok = bool(overwrite and int(overwrite.get("deny", "0")) & VIEW)
            verified[channel["name"]] = ok

        if not all(verified.values()):
            bad = sorted(name for name, ok in verified.items() if not ok)
            raise RuntimeError("PLAYBOOK_PERMISSION_VERIFY_FAILED_" + ",".join(bad[:5]))

        test_result = {"status": "NOT_RUN"}
        if test:
            # Playbook may intentionally ignore bot-authored messages. A response proves
            # end-to-end command handling; no response is reported separately from the
            # permission verification above.
            priority = ["jabbazi-picks", "daily-card", "nfl-picks"]
            target = next(
                (c for name in priority for c in targets if c["name"] == name),
                targets[0],
            )
            message = request(
                http,
                "POST",
                f"/channels/{target['id']}/messages",
                {
                    "content": (
                        "PLAYBOOK CONNECTIVITY TEST — no wager is being placed. "
                        f"<@{playbook_user_id}> DraftKings"
                    ),
                    "allowed_mentions": {"users": [playbook_user_id], "parse": []},
                },
            )
            test_id = str(message["id"])
            response_message = None
            for _ in range(12):
                time.sleep(1)
                recent = request(
                    http,
                    "GET",
                    f"/channels/{target['id']}/messages?limit=20",
                )
                response_message = next(
                    (
                        m for m in recent
                        if str(m.get("author", {}).get("id")) == playbook_user_id
                        and int(str(m["id"])) > int(test_id)
                    ),
                    None,
                )
                if response_message:
                    break
            # Always remove our own test message.
            try:
                request(http, "DELETE", f"/channels/{target['id']}/messages/{test_id}")
            except Exception:
                pass
            test_result = {
                "status": "RESPONDED" if response_message else "NO_RESPONSE_TO_BOT_AUTHORED_TEST",
                "channel": target["name"],
            }

        return {
            **plan,
            "status": "VERIFIED",
            "role_permissions": 0,
            "verified_channel_overwrites": len(verified),
            "test": test_result,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    try:
        result = configure(apply=args.apply, test=args.test)
        print("PLAYBOOK_CONFIGURATION " + json.dumps(result, separators=(",", ":")), flush=True)
        return 0
    except Exception as exc:
        # Never print token, request bodies, or Discord error payloads.
        print(
            "PLAYBOOK_CONFIGURATION "
            + json.dumps(
                {"status": "UNAVAILABLE", "error": str(exc)[:180]},
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

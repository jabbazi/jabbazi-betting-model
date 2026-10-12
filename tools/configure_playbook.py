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

# Strict production allowlist. These are the only active wager/update channels in
# the current server blueprint. Research, cheat sheets, chat, archived picks and
# staff channels are intentionally excluded.
TARGET_EXACT = {"main-card", "live-watch"}
TARGET_CATEGORY = "TODAY’S JABBAZI"


def request(http: httpx.Client, method: str, path: str, payload=None):
    operation = method + "_" + path.rsplit("/", 1)[-1].upper()
    for _ in range(4):
        response = http.request(method, path, json=payload)
        if response.status_code == 429:
            retry = float(response.json().get("retry_after", 1))
            if retry > 20:
                raise RuntimeError("PLAYBOOK_RATE_LIMIT_TOO_LONG")
            time.sleep(max(0.2, retry))
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise RuntimeError(
                f"PLAYBOOK_{operation}_HTTP_{response.status_code}"
            ) from None
        if response.status_code == 204 or not response.content:
            return None
        return response.json()
    raise RuntimeError("PLAYBOOK_RATE_LIMIT_PERSISTED")


def canonical_channel_name(name: str) -> str:
    # Display names are emoji-prefixed, e.g. "🎯│jabbazi-main-card".
    return name.rsplit("│", 1)[-1].strip().lower()


def target_channels(channels):
    categories = {str(c["id"]): c["name"] for c in channels if c.get("type") == 4}
    targets = []
    for channel in channels:
        if channel.get("type") not in (0, 5):
            continue
        name = canonical_channel_name(channel.get("name", ""))
        parent = categories.get(str(channel.get("parent_id")), "")
        if name in TARGET_EXACT and TARGET_CATEGORY in parent:
            targets.append(channel)
    return targets, categories


def member_base_permissions(roles, member_roles, guild_id):
    role_ids = {str(r) for r in member_roles}
    role_ids.add(str(guild_id))
    permissions = 0
    for role in roles:
        if str(role["id"]) in role_ids:
            permissions |= int(role.get("permissions", "0"))
    return permissions


def effective_channel_permissions(base, channel, member_roles, member_id, guild_id):
    if base & ADMINISTRATOR:
        return (1 << 53) - 1

    permissions = base
    overwrites = channel.get("permission_overwrites", [])

    everyone = next(
        (
            p for p in overwrites
            if int(p.get("type", -1)) == 0 and str(p.get("id")) == str(guild_id)
        ),
        None,
    )
    if everyone:
        permissions &= ~int(everyone.get("deny", "0"))
        permissions |= int(everyone.get("allow", "0"))

    role_ids = {str(r) for r in member_roles}
    role_deny = 0
    role_allow = 0
    for overwrite in overwrites:
        if int(overwrite.get("type", -1)) != 0:
            continue
        oid = str(overwrite.get("id"))
        if oid == str(guild_id) or oid not in role_ids:
            continue
        role_deny |= int(overwrite.get("deny", "0"))
        role_allow |= int(overwrite.get("allow", "0"))
    permissions &= ~role_deny
    permissions |= role_allow

    member = next(
        (
            p for p in overwrites
            if int(p.get("type", -1)) == 1 and str(p.get("id")) == str(member_id)
        ),
        None,
    )
    if member:
        permissions &= ~int(member.get("deny", "0"))
        permissions |= int(member.get("allow", "0"))

    return permissions


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
            return {
                "status": "NEEDS_TARGET_DISCOVERY",
                "playbook_role": role.get("name"),
                "channels": [
                    {
                        "name": ch.get("name", ""),
                        "type": ch.get("type"),
                        "category": categories.get(str(ch.get("parent_id")), ""),
                    }
                    for ch in channels
                    if ch.get("type") in (0, 5)
                ][:80],
            }
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

        # Deny every currently visible non-target text/announcement channel.
        # We do this per channel instead of requiring access to every category; private
        # staff/archive areas that Playbook already cannot view need no write.
        member = request(http, "GET", f"/guilds/{guild}/members/{playbook_user_id}")
        member_roles = [str(r) for r in member.get("roles", [])]
        post_role_channels = request(http, "GET", f"/guilds/{guild}/channels")
        base_permissions = member_base_permissions(roles, member_roles, guild)

        write_failures = []
        category_fallbacks = {}
        attempted_parent_denies = set()
        channel_by_id = {str(ch["id"]): ch for ch in post_role_channels}
        for channel in [c for c in post_role_channels if c.get("type") in (0, 5)]:
            if str(channel["id"]) in target_ids:
                continue
            effective = effective_channel_permissions(
                base_permissions,
                channel,
                member_roles,
                playbook_user_id,
                guild,
            )
            if not (effective & VIEW):
                continue
            try:
                request(
                    http,
                    "PUT",
                    f"/channels/{channel['id']}/permissions/{role_id}",
                    {"type": 0, "allow": "0", "deny": str(VIEW)},
                )
            except RuntimeError as exc:
                # First try a member-specific overwrite. This is narrower than touching
                # the category and avoids managed-role restrictions on some Discord channels.
                try:
                    request(
                        http,
                        "PUT",
                        f"/channels/{channel['id']}/permissions/{playbook_user_id}",
                        {"type": 1, "allow": "0", "deny": str(VIEW)},
                    )
                    fallback_status = "MEMBER_DENY_APPLIED"
                except RuntimeError as member_exc:
                    parent_id = str(channel.get("parent_id") or "")
                    fallback_status = "MEMBER_DENY_FAILED_" + str(member_exc)
                    if parent_id and parent_id not in attempted_parent_denies:
                        attempted_parent_denies.add(parent_id)
                        parent = channel_by_id.get(parent_id)
                        try:
                            request(
                                http,
                                "PUT",
                                f"/channels/{parent_id}/permissions/{role_id}",
                                {"type": 0, "allow": "0", "deny": str(VIEW)},
                            )
                            fallback_status += "_CATEGORY_DENY_APPLIED"
                        except RuntimeError as parent_exc:
                            fallback_status += "_CATEGORY_DENY_FAILED_" + str(parent_exc)
                        category_fallbacks[parent_id] = {
                            "category": parent.get("name") if parent else "",
                            "status": fallback_status,
                        }
                    elif parent_id:
                        fallback_status += "_" + category_fallbacks.get(
                            parent_id, {}
                        ).get("status", "CATEGORY_ALREADY_ATTEMPTED")
                write_failures.append(
                    {
                        "id": str(channel["id"]),
                        "name": channel["name"],
                        "error": str(exc),
                        "fallback": fallback_status,
                    }
                )

        # Grant only the exact minimum on approved VIP pick/parlay channels.
        for channel in targets:
            request(
                http,
                "PUT",
                f"/channels/{channel['id']}/permissions/{role_id}",
                {"type": 0, "allow": str(TARGET_ALLOW), "deny": "0"},
            )

        # Read back the live role and compute effective access for the Playbook member.
        live_roles = request(http, "GET", f"/guilds/{guild}/roles")
        live_role = next(r for r in live_roles if str(r["id"]) == role_id)
        if int(live_role.get("permissions", "0")) != 0:
            raise RuntimeError("PLAYBOOK_ROLE_PERMISSION_REDUCTION_FAILED")

        live_member = request(http, "GET", f"/guilds/{guild}/members/{playbook_user_id}")
        live_member_roles = [str(r) for r in live_member.get("roles", [])]
        live_channels = request(http, "GET", f"/guilds/{guild}/channels")
        live_base = member_base_permissions(live_roles, live_member_roles, guild)

        verified = {}
        unwanted_visible = []
        readonly_public_exceptions = []
        target_permission_failures = []
        for channel in [c for c in live_channels if c.get("type") in (0, 5)]:
            effective = effective_channel_permissions(
                live_base,
                channel,
                live_member_roles,
                playbook_user_id,
                guild,
            )
            is_target = str(channel["id"]) in target_ids
            if is_target:
                ok = (effective & TARGET_ALLOW) == TARGET_ALLOW
                if not ok:
                    target_permission_failures.append(channel["name"])
            else:
                visible = bool(effective & VIEW)
                can_send = bool(effective & SEND)
                canonical = canonical_channel_name(channel.get("name", ""))
                is_public_welcome = canonical == "welcome" and not can_send
                if not visible:
                    ok = True
                elif is_public_welcome:
                    # Discord refuses an overwrite on this legacy public read-only
                    # channel. It remains visible like it is to every member, but the
                    # bot cannot post/operate there.
                    ok = True
                    readonly_public_exceptions.append(channel["name"])
                else:
                    ok = False
                    unwanted_visible.append(channel["name"])
            verified[channel["name"]] = ok

        if target_permission_failures or unwanted_visible:
            details = {
                "targets_missing_permissions": target_permission_failures[:5],
                "unexpected_visible_channels": unwanted_visible[:10],
                "readonly_public_exceptions": readonly_public_exceptions[:5],
                "write_failures": write_failures[:5],
            }
            raise RuntimeError(
                "PLAYBOOK_EFFECTIVE_PERMISSION_VERIFY_FAILED_"
                + json.dumps(details, separators=(",", ":"))
            )

        test_result = {"status": "NOT_RUN"}
        if test:
            # Playbook may intentionally ignore bot-authored messages. A response proves
            # end-to-end command handling; no response is reported separately from the
            # permission verification above.
            priority = ["main-card", "live-watch"]
            target = next(
                (
                    channel
                    for name in priority
                    for channel in targets
                    if canonical_channel_name(channel["name"]) == name
                ),
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
            "verified_channels": len(verified),
            "permission_write_failures_resolved_by_effective_check": len(write_failures),
            "category_fallbacks": category_fallbacks,
            "readonly_public_exceptions": readonly_public_exceptions,
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
                {"status": "UNAVAILABLE", "error": str(exc)[:1500]},
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

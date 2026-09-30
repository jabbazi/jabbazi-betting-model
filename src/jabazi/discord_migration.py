"""Backup-first, non-destructive Discord migration and permission verification."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .discord_access import vip_role_ids
from .persistence.store import Store, digest

VIEW = 1 << 10
SEND = 1 << 11
READ = 1 << 16
MANAGE_CHANNELS = 1 << 4
MANAGE_ROLES = 1 << 28
ADMIN = 1 << 3
THREAD_SEND = 1 << 38
THREAD_CREATE = 1 << 36
PIN_MESSAGES = 1 << 51
APP_COMMANDS = 1 << 31
POSTING = SEND | (1 << 35) | THREAD_CREATE | THREAD_SEND
BOT_CHANNEL = VIEW | SEND | READ | (1 << 13) | (1 << 14) | (1 << 15) | THREAD_SEND | THREAD_CREATE | (1 << 35)
STAFF_NAMES = {"JABBAZI TEAM", "MODERATOR"}
ARCHIVE = "🗄️ ARCHIVE"
CHANNEL_ENV = {
    "scanner-status": "STATUS_CHANNEL_ID",
    "daily-moneyline-cheat-sheet": "SHEETS_CHANNEL_ID",
    "jabbazi-main-card": "MAIN_CARD_CHANNEL_ID",
    "results": "RESULTS_CHANNEL_ID",
    "support": "SUPPORT_CHANNEL_ID",
    "vip-research": "VIP_RESEARCH_CHANNEL_ID",
    "market-watch": "MARKET_WATCH_CHANNEL_ID",
    "welcome": "WELCOME_CHANNEL_ID",
    "how-to-use-jabbazi": "GUIDE_CHANNEL_ID",
    "get-access": "ACCESS_CHANNEL_ID",
    "general": "GENERAL_CHANNEL_ID",
    "bot-log": "BOT_LOG_CHANNEL_ID",
}


def channel_name(name):
    """Match observed legacy emoji/separator prefixes without changing history."""
    return re.sub(r"^[^a-z0-9]+", "", name.lower())


def configured_vip_ids():
    values = [os.getenv("JABBAZI_DISCORD_VIP_ROLE_ID", ""),
              os.getenv("JABBAZI_DISCORD_BILLING_ROLE_ID", "")]
    values += os.getenv("JABBAZI_DISCORD_VIEWER_ROLE_IDS", "").split(",")
    return [v.strip() for v in values if v.strip().isdigit()]


def overwrites(access, *, guild, owner, bot, vip, staff, read_only=False):
    rows = [{"id": str(guild), "type": 0,
             "allow": str(VIEW | READ | APP_COMMANDS | (0 if read_only else SEND | THREAD_SEND | (1 << 35))) if access == "public" else "0",
             "deny": str((0 if access == "public" else VIEW) | (POSTING if read_only else 0))}]
    for role in (set(vip) if access == "vip" else set()) | set(staff):
        rows.append({"id": str(role), "type": 0, "allow": str(VIEW | READ | APP_COMMANDS | (0 if read_only else SEND | THREAD_SEND | (1 << 35))),
                     "deny": str(POSTING) if read_only else "0"})
    # Server ownership already bypasses channel restrictions. An explicit owner
    # member allow also survives Discord's View Server As Role preview and masks
    # the role's actual restrictions, so only the bot needs a member overwrite.
    for member, permissions in ((bot, BOT_CHANNEL),):
        rows.append({"id": str(member), "type": 1, "allow": str(permissions), "deny": "0"})
    return rows


def effective_permissions(guild, member, role_ids, roles, channel, owner):
    if str(member) == str(owner):
        return (1 << 53) - 1
    selected = {str(guild), *(str(r) for r in role_ids)}
    permissions = 0
    for role in roles:
        if str(role["id"]) in selected:
            permissions |= int(role.get("permissions", 0))
    if permissions & ADMIN:
        return (1 << 53) - 1
    entries = channel.get("permission_overwrites", [])
    for row in entries:
        if str(row["id"]) == str(guild) and row["type"] == 0:
            permissions = (permissions & ~int(row["deny"])) | int(row["allow"])
    deny = allow = 0
    for row in entries:
        if row["type"] == 0 and str(row["id"]) in selected - {str(guild)}:
            deny |= int(row["deny"])
            allow |= int(row["allow"])
    permissions = (permissions & ~deny) | allow
    for row in entries:
        if row["type"] == 1 and str(row["id"]) == str(member):
            permissions = (permissions & ~int(row["deny"])) | int(row["allow"])
    return permissions


def request(http, method, path, operation, **kwargs):
    # Discord explicitly rejected a rate-limited request: bounded retry is safe.
    # Transport/5xx mutations are never blindly replayed.
    for attempt in range(3):
        response = http.request(method, path, **kwargs)
        if response.status_code != 429:
            break
        delay = min(float(response.json().get("retry_after", 1)), 10)
        if attempt < 2:
            time.sleep(max(0, delay))
    if response.status_code >= 400:
        code = response.json().get("code") if response.headers.get("content-type", "").startswith("application/json") else None
        detail = f"DISCORD_OPERATION_{operation}_HTTP_{response.status_code}_PATH_{path}_CODE_{code if isinstance(code, int) else 'UNKNOWN'}"
        print(detail, flush=True)
        raise RuntimeError(detail)
    return response.json() if response.content else None


def migrate(*, apply=False, archive_obsolete=False):
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "")
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "")
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "")
    if not token or not guild.isdigit() or not owner.isdigit():
        raise ValueError("Discord token, guild ID and owner ID are required")
    bp = json.loads(Path("docs/discord/server_blueprint.json").read_text())
    with httpx.Client(base_url="https://discord.com/api/v10", timeout=20,
                      headers={"Authorization": "Bot " + token}) as http:
        def call(method, path, operation, **kwargs):
            return request(http, method, path, operation, **kwargs)
        info = call("GET", f"/guilds/{guild}", "READ_GUILD")
        if str(info["owner_id"]) != owner:
            raise ValueError("Configured Discord owner mismatch")
        me = call("GET", "/users/@me", "READ_BOT")
        bot = str(me["id"])
        roles = call("GET", f"/guilds/{guild}/roles", "READ_ROLES")
        channels = call("GET", f"/guilds/{guild}/channels", "READ_CHANNELS")
        membership = call("GET", f"/guilds/{guild}/members/{bot}", "READ_BOT_MEMBERSHIP")
        application = call("GET", "/oauth2/applications/@me", "READ_APPLICATION")
        commands = call("GET", f"/applications/{application['id']}/guilds/{guild}/commands", "READ_COMMANDS")
        vip = vip_role_ids(roles, configured_vip_ids())
        if not vip:
            raise ValueError("No approved VIP-family role exists")
        staff = {str(r["id"]) for r in roles if r["name"].upper() in STAFF_NAMES}
        bot_roles = [r for r in roles if str(r["id"]) in membership["roles"]]
        top = max((r.get("position", 0) for r in bot_roles), default=0)
        permissions = effective_permissions(guild, bot, membership["roles"], roles, {}, owner)
        warnings = []
        if permissions & ADMIN:
            warnings.append("BOT_HAS_ADMINISTRATOR: owner must review role before completion")
        high = [str(r["id"]) for r in roles if (str(r["id"]) in vip or r["name"].endswith(" Alerts")) and r.get("position", 0) >= top]
        if high:
            warnings.append("BOT_ROLE_NOT_ABOVE_MANAGED_ROLES: " + ",".join(high))
        plan = {"mode": "APPLIED" if apply else "DRY_RUN", "guild_id": guild,
                "warnings": warnings, "actions": [], "channel_ids": {}, "verification": []}
        for name, suffix in CHANNEL_ENV.items():
            configured = os.getenv("JABBAZI_DISCORD_" + suffix, "")
            if configured and not any(c["type"] == 0 and str(c["id"]) == configured for c in channels):
                raise ValueError(f"Configured channel ID missing for {name}; review before migration")
        if apply:
            if not permissions & ADMIN and permissions & (MANAGE_CHANNELS | MANAGE_ROLES) != MANAGE_CHANNELS | MANAGE_ROLES:
                raise ValueError("Bot requires Manage Channels and Manage Roles before permission repair")
            url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
            if not url:
                raise ValueError("Durable database backup is required before migration")
            store = Store(url)
            try:
                if not store.ready():
                    raise ValueError("Backup database is not ready")
                from .discord_onboarding import introduction_snapshot
                guide_names = {n for c in bp["categories"] for n in c["channels"]}
                guide_names |= {alias for aliases in bp.get("channel_aliases", {}).values() for alias in aliases}
                introductions = [introduction_snapshot(http, str(c["id"]), bot) for c in channels
                                 if c["type"] == 0 and channel_name(c["name"]) in guide_names
                                 and effective_permissions(guild, bot, membership["roles"], roles, c, owner) & VIEW]
                snapshot = {"captured_at": datetime.now(UTC).isoformat(), "guild": info,
                            "roles": roles, "channels": channels, "bot_membership": membership,
                            "application": {"id": application["id"], "name": application.get("name"), "flags": application.get("flags", 0)},
                            "commands": commands, "introductions": introductions}
                key = digest(["discord_server_backup", snapshot])
                store.append("discord_server_backup", guild, snapshot, key)
                saved = store.list_records("discord_server_backup", 1, entity=guild)
                if not saved or saved[0]["id"] != key:
                    raise RuntimeError("Discord backup readback failed")
                plan["backup_id"] = key
                print(f"DISCORD_BACKUP_VERIFIED {key} CHANNELS={len(channels)} ROLES={len(roles)} BOT={bot}", flush=True)
            finally:
                store.close()

        def desired(access, read_only=False, archive=False):
            rows = overwrites(access, guild=guild, owner=owner, bot=bot, vip=vip, staff=staff, read_only=read_only)
            if permissions & PIN_MESSAGES:
                next(row for row in rows if row["type"] == 1 and row["id"] == bot)["allow"] = str(BOT_CHANNEL | PIN_MESSAGES)
            if archive:
                # Historical archives need visibility/history only. Do not try
                # to grant posting/thread bits denied to the bot in old read-only
                # channels; Discord rejects such overwrite mutations with 403.
                for row in rows:
                    row["allow"] = str(int(row["allow"]) & (VIEW | READ))
            return rows

        def upsert(existing, payload, operation):
            if existing and all(existing.get(k) == v for k, v in payload.items()):
                return existing
            plan["actions"].append({"operation": operation, "name": payload.get("name", existing.get("name") if existing else None),
                                    "id": existing.get("id") if existing else None})
            if apply:
                if existing:
                    try:
                        result = call("PATCH", f"/channels/{existing['id']}", operation, json=payload)
                    except RuntimeError:
                        current = effective_permissions(guild, bot, membership["roles"], roles, existing, owner)
                        print(f"DISCORD_CHANNEL_FAILURE ID={existing['id']} BOT={bot} VIEW={bool(current & VIEW)} MANAGE_CHANNELS={bool(current & MANAGE_CHANNELS)} MANAGE_ROLES={bool(current & MANAGE_ROLES)}", flush=True)
                        raise
                else:
                    result = call("POST", f"/guilds/{guild}/channels", operation, json=payload)
                return result
            return {**(existing or {"id": "planned:" + payload["name"]}), **payload}

        used = set()
        targets = []
        aliases = bp.get("channel_aliases", {})
        for position, category in enumerate(bp["categories"]):
            existing = next((c for c in channels if c["type"] == 4 and c["name"] in [category["name"], *bp.get("category_aliases", {}).get(category["name"], [])]), None)
            parent = upsert(existing, {"name": category["name"], "type": 4, "position": position,
                                      "permission_overwrites": desired(category["access"])}, "UPSERT_CATEGORY")
            used.add(str(parent["id"]))
            targets.append((parent, category["access"]))
            for order, name in enumerate(category["channels"]):
                configured = os.getenv("JABBAZI_DISCORD_" + CHANNEL_ENV[name], "") if name in CHANNEL_ENV else ""
                # The production status ID points at an intentionally owner-only
                # legacy archive. Never republish that private history to VIPs.
                if name == "scanner-status" and any(str(c["id"]) == configured and channel_name(c["name"]) == "owner-archive" for c in channels):
                    plan["warnings"].append("STALE_STATUS_ID_OWNER_ARCHIVE_PRESERVED")
                    configured = ""
                exact = [c for c in channels if c["type"] == 0 and str(c["id"]) not in used]
                existing = next((c for c in exact if str(c["id"]) == configured), None) if configured else None
                if configured and existing is None:
                    raise ValueError(f"Configured channel ID missing for {name}; review before migration")
                if existing is None:
                    existing = next((c for c in exact if channel_name(c["name"]) == name), None)
                if existing is None:
                    existing = next((c for c in exact if channel_name(c["name"]) in aliases.get(name, [])), None)
                channel_permissions = desired(category["access"], name in bp.get("read_only_channels", []))
                if name == "support":
                    for row in channel_permissions:
                        if row["type"] == 0:
                            row["allow"] = str(int(row["allow"]) & ~(SEND | (1 << 35) | THREAD_CREATE))
                            row["deny"] = str(int(row["deny"]) | SEND | (1 << 35) | THREAD_CREATE)
                channel = upsert(existing, {"name": bp.get("channel_display_names", {}).get(name, name), "type": 0, "parent_id": parent["id"], "position": order,
                    "permission_overwrites": channel_permissions,
                    "topic": bp.get("channel_topics", {}).get(name, ""),
                    "rate_limit_per_user": 5 if name in {"general", "sports-talk", "vip-lounge", "live-watch"} else 0}, "UPSERT_CHANNEL")
                used.add(str(channel["id"]))
                plan["channel_ids"][name] = str(channel["id"])
                targets.append((channel, category["access"]))
        if archive_obsolete:
            def preserve_hidden(channel):
                if effective_permissions(guild, bot, membership["roles"], roles, channel, owner) & VIEW:
                    return False
                ordinary_visible = effective_permissions(guild, "free-simulation", [], roles, channel, owner) & VIEW
                vip_visible = any(effective_permissions(guild, "vip-simulation", [role], roles, channel, owner) & VIEW for role in vip)
                if ordinary_visible or vip_visible:
                    return False
                plan["warnings"].append("PRESERVED_ALREADY_HIDDEN_LEGACY: " + str(channel["id"]))
                return True
            # Only managed/known legacy channels; never delete content or unknown integrations.
            old_parents = {str(c["id"]) for c in channels if c["type"] == 4 and c["name"].startswith(("━━", "╰➤"))}
            legacy_names = set(bp.get("deprecated_channels", [])) | set(plan["channel_ids"])
            obsolete = [c for c in channels if c["type"] != 4 and str(c["id"]) not in used
                        and channel_name(c["name"]) != "owner-archive"
                        and (channel_name(c["name"]) in legacy_names or str(c.get("parent_id")) in old_parents)]
            if obsolete:
                archive = next((c for c in channels if c["type"] == 4 and c["name"] in {ARCHIVE, "━━ ARCHIVE ━━"}), None)
                archive = upsert(archive, {"name": ARCHIVE, "type": 4, "position": 99,
                                          "permission_overwrites": desired("staff", archive=True)}, "UPSERT_ARCHIVE")
                for channel in obsolete:
                    if preserve_hidden(channel):
                        continue
                    try:
                        archived = upsert(channel, {"parent_id": archive["id"], "permission_overwrites": desired("staff", archive=True)}, "ARCHIVE_CHANNEL")
                    except RuntimeError as exc:
                        plan["warnings"].append(str(exc))
                        continue
                    targets.append((archived, "staff"))
            for category in channels:
                if category["type"] == 4 and str(category["id"]) not in used and str(category["id"]) in old_parents:
                    if preserve_hidden(category):
                        continue
                    try:
                        hidden = upsert(category, {"permission_overwrites": desired("staff", archive=True)}, "HIDE_OLD_CATEGORY")
                    except RuntimeError as exc:
                        plan["warnings"].append(str(exc))
                        continue
                    targets.append((hidden, "staff"))
        # Discord category positions share one global list. Place every active
        # category first in a single reorder, with preserved legacy categories
        # after them, instead of interleaving old categories during upserts.
        if apply:
            ordered = call("GET", f"/guilds/{guild}/channels", "READ_CATEGORY_ORDER")
            active_names = [category["name"] for category in bp["categories"]]
            # Delete only backed-up, provably empty legacy headings. Messages,
            # text/voice channels and nonempty owner-only categories are preserved.
            for old in list(ordered):
                if old["type"] != 4 or old["name"] in active_names or old["name"] == ARCHIVE:
                    continue
                if not old["name"].startswith(("━━", "╰➤", "🗄️ ARCHIVE ·")):
                    continue
                children = [c for c in ordered if str(c.get("parent_id")) == str(old["id"])]
                try:
                    if not children and effective_permissions(guild, bot, membership["roles"], roles, old, owner) & VIEW:
                        call("DELETE", f"/channels/{old['id']}", "REMOVE_EMPTY_LEGACY_CATEGORY")
                        ordered.remove(old)
                        targets = [(c, a) for c, a in targets if str(c["id"]) != str(old["id"])]
                    elif not old["name"].startswith("🗄️ ARCHIVE ·") and effective_permissions(guild, bot, membership["roles"], roles, old, owner) & VIEW:
                        renamed = call("PATCH", f"/channels/{old['id']}", "LABEL_LEGACY_ARCHIVE", json={"name": "🗄️ ARCHIVE · " + old["name"].strip("━╰➤ ")[:75]})
                        old.update(renamed)
                        targets = [(old if str(c["id"]) == str(old["id"]) else c, a) for c, a in targets]
                except RuntimeError as exc:
                    plan["warnings"].append(str(exc))
            active = [next(c for c in ordered if c["type"] == 4 and c["name"] == name) for name in active_names]
            legacy = sorted([c for c in ordered if c["type"] == 4 and c["name"] not in active_names], key=lambda c: c.get("position", 0))
            call("PATCH", f"/guilds/{guild}/channels", "ORDER_CATEGORIES", json=[{"id": c["id"], "position": position} for position, c in enumerate(active + legacy)])
        # Create only missing opt-in alerts; no duplicate VIP-family roles.
        for spec in bp["roles"]:
            if not spec["name"].endswith(" Alerts") or any(r["name"] == spec["name"] for r in roles):
                continue
            plan["actions"].append({"operation": "CREATE_ALERT_ROLE", "name": spec["name"]})
            if apply:
                call("POST", f"/guilds/{guild}/roles", "CREATE_ALERT_ROLE", json={"name": spec["name"], "permissions": "0", "mentionable": False})
        if apply:
            live = call("GET", f"/guilds/{guild}/channels", "VERIFY_CHANNELS")
            category_order = [c["name"] for c in sorted((c for c in live if c["type"] == 4), key=lambda c: c.get("position", 0))]
            expected_order = [c["name"] for c in bp["categories"]]
            if category_order[:len(expected_order)] != expected_order:
                raise RuntimeError("Discord active category order verification failed")
            print("DISCORD_CATEGORY_ORDER_VERIFIED " + json.dumps(category_order, ensure_ascii=False), flush=True)
            by_id = {str(c["id"]): c for c in live}
            for target, access in targets:
                actual = by_id[str(target["id"])]
                if actual.get("parent_id") != target.get("parent_id") or actual["name"] != target["name"] or actual.get("topic") != target.get("topic"):
                    print("DISCORD_VERIFY_CHANNEL_MISMATCH " + json.dumps({"id": actual["id"], "actual_name": actual["name"], "expected_name": target["name"], "parent_matches": actual.get("parent_id") == target.get("parent_id"), "topic_matches": actual.get("topic") == target.get("topic")}, ensure_ascii=False), flush=True)
                    raise RuntimeError("Discord channel readback mismatch")
                free = bool(effective_permissions(guild, "free-simulation", [], roles, actual, owner) & VIEW)
                if free != (access == "public"):
                    print(f"DISCORD_VERIFY_FREE_FAILED CHANNEL={actual['id']} EXPECTED_ACCESS={access}", flush=True)
                    raise RuntimeError("Discord free-member permission verification failed")
                for role in vip:
                    visible = bool(effective_permissions(guild, "vip-simulation", [role], roles, actual, owner) & VIEW)
                    if visible != (access != "staff"):
                        print(f"DISCORD_VERIFY_VIP_FAILED CHANNEL={actual['id']} ROLE={role} EXPECTED_ACCESS={access}", flush=True)
                        raise RuntimeError("Discord VIP permission verification failed")
                canonical = channel_name(actual["name"])
                if str(actual["id"]) in set(plan["channel_ids"].values()) and canonical in bp.get("read_only_channels", []):
                    for assigned in ([], *[[r] for r in vip], list(vip)):
                        member_permissions = effective_permissions(guild, "readonly-simulation", assigned, roles, actual, owner)
                        if member_permissions & POSTING:
                            print(f"DISCORD_VERIFY_READ_ONLY_FAILED CHANNEL={actual['id']} ROLES={assigned} POSTING_BITS={member_permissions & POSTING}", flush=True)
                            raise RuntimeError("Discord read-only thread permission verification failed")
                    for role in staff:
                        staff_permissions = effective_permissions(guild, "staff-readonly-simulation", [role], roles, actual, owner)
                        # Administrators inherently bypass channel restrictions;
                        # ordinary moderators must still respect publishing rules.
                        if not staff_permissions & ADMIN and staff_permissions & POSTING:
                            print(f"DISCORD_VERIFY_STAFF_READ_ONLY_FAILED CHANNEL={actual['id']} ROLE={role}", flush=True)
                            raise RuntimeError("Discord moderator read-only verification failed")
                for role in staff:
                    if not effective_permissions(guild, "mod-simulation", [role], roles, actual, owner) & VIEW:
                        print(f"DISCORD_VERIFY_MODERATOR_FAILED CHANNEL={actual['id']} ROLE={role}", flush=True)
                        raise RuntimeError("Discord moderator visibility verification failed")
                if not effective_permissions(guild, bot, membership["roles"], roles, actual, owner) & VIEW:
                    print(f"DISCORD_VERIFY_BOT_FAILED CHANNEL={actual['id']}", flush=True)
                    raise RuntimeError("Discord bot access verification failed")
                plan["verification"].append({"id": str(actual["id"]), "access": access, "status": "VERIFIED"})
            for original in channels:
                if channel_name(original["name"]) == "owner-archive":
                    if by_id[str(original["id"])].get("permission_overwrites") != original.get("permission_overwrites"):
                        raise RuntimeError("Owner-only archive permission preservation failed")
                    for role in staff | vip:
                        role_permissions = effective_permissions(guild, "owner-archive-simulation", [role], roles, by_id[str(original["id"])], owner)
                        if not role_permissions & ADMIN and role_permissions & VIEW:
                            print(f"DISCORD_VERIFY_OWNER_ARCHIVE_FAILED CHANNEL={original['id']} ROLE={role}", flush=True)
                            raise RuntimeError("Owner-only archive exposed to member/staff role")
            print(f"DISCORD_ROLE_HIERARCHY_VERIFIED={not bool(high)} BOT_TOP_POSITION={top}", flush=True)
            print(f"DISCORD_PERMISSIONS_VERIFIED ACTIVE={len(plan['channel_ids'])} VIP_ROLES={len(vip)} READ_ONLY_THREADS_BLOCKED=TRUE BOT_ADMIN={bool(permissions & ADMIN)} BOT_PIN={bool(permissions & PIN_MESSAGES)}", flush=True)
        return plan

"""Separate billing-source roles from manual VIP grants and rules acceptance."""
import json
import os

import httpx

from .discord_access import normalize_role_name
from .discord_migration import MANAGE_ROLES, request
from .discord_rules import CONFIG_KEY, configuration
from .persistence.store import digest

WHOP_BOT_ID = "815703008075579422"
WHOP_SOURCE_NAME = "JABBAZI WHOP SUBSCRIBER"
WHOP_ALLOWED_PERMISSIONS = MANAGE_ROLES | 1 | (1 << 10) | (1 << 11) | (1 << 14)


class WhopSetupError(ValueError):
    """Controlled preflight reason safe for operational logs (no provider body)."""

    def __init__(self, code):
        super().__init__(code)
        self.safe_code = code


def role_below(role, other, guild):
    """Discord orders equal positions by descending snowflake; everyone is last."""
    rid, oid = str(role["id"]), str(other["id"])
    if rid == oid or oid == str(guild):
        return False
    if rid == str(guild):
        return True
    return (int(role["position"]), -int(rid)) < (int(other["position"]), -int(oid))


def subscription_sources(config):
    """Only direct aliases to an existing, independently gated paid tier qualify."""
    tiers = config.get("paid_roles", {})
    return {
        str(source): str(tier)
        for source, tier in config.get("subscription_sources", {}).items()
        if str(source).isdigit() and str(tier) in tiers
        and str(source) not in set(config.get("source_vip", []))
        and str(source) not in set(tiers.values())
        and str(source) not in {config.get("community_role"), config.get("paid_role"), config.get("guild")}
    }


def paid_source_roles(config, held):
    held = set(map(str, held))
    # Never assign the original/manual source role. The union affects only the
    # derived gate calculation, so cancellation cannot erase a manual grant.
    return held | {tier for source, tier in subscription_sources(config).items() if source in held}


def install_whop_source(store):
    """Opt-in, audited mapping; no member edits, channel changes, or role reordering."""
    if os.getenv("JABBAZI_WHOP_SETUP_ENABLED", "false").lower() != "true":
        return {"status": "DISABLED"}
    config = configuration(store)
    guild = os.environ["JABBAZI_DISCORD_GUILD_ID"]
    owner = os.environ["JABBAZI_DISCORD_OWNER_ID"]
    if not config or config["guild"] != guild or config["owner"] != owner:
        raise ValueError("An active rules gate for the configured owner is required")
    with httpx.Client(base_url="https://discord.com/api/v10", timeout=20,
                      headers={"Authorization": "Bot " + os.environ["JABBAZI_DISCORD_BOT_TOKEN"]}) as http:
        info = request(http, "GET", f"/guilds/{guild}", "WHOP_GUILD")
        if str(info["owner_id"]) != owner:
            raise ValueError("Owner mismatch")
        roles = request(http, "GET", f"/guilds/{guild}/roles", "WHOP_ROLES")
        channels = request(http, "GET", f"/guilds/{guild}/channels", "WHOP_CHANNELS")
        references = [r for r in roles if normalize_role_name(r["name"]) == "JABBAZI VIP"]
        bots = [r for r in roles if str(r.get("tags", {}).get("bot_id", "")) == WHOP_BOT_ID]
        if len(references) != 1 or len(bots) != 1:
            raise ValueError("Expected unique existing VIP tier and installed Whop bot")
        reference, bot_role = references[0], bots[0]
        tier = str(reference["id"])
        if tier not in config.get("paid_roles", {}) or reference.get("managed"):
            raise ValueError("VIP tier is not registered with the rules gate")
        derived = [r for r in roles if str(r["id"]) == config["paid_roles"][tier]]
        if len(derived) != 1 or derived[0].get("managed") or int(derived[0]["permissions"]):
            raise ValueError("Existing derived tier is not least privilege")
        bot_permissions = int(bot_role["permissions"])
        if not bot_permissions & MANAGE_ROLES or bot_permissions & ~WHOP_ALLOWED_PERMISSIONS:
            raise ValueError("Whop permissions differ from the approved limited scope")
        sources = [r for r in roles if r["name"] == WHOP_SOURCE_NAME]
        if len(sources) > 1:
            raise ValueError("Duplicate Whop source roles")
        backup = {"config": config, "roles": roles, "channels": channels}
        backup_id = digest(["whop_setup_backup", guild, backup])
        if not sources:
            store.append("whop_setup_backup", guild, backup, backup_id)
            if not any(r["id"] == backup_id for r in store.list_records("whop_setup_backup", 20, entity=guild)):
                raise RuntimeError("Whop setup backup readback failed")
            source = request(http, "POST", f"/guilds/{guild}/roles", "WHOP_CREATE_SOURCE",
                             json={"name": WHOP_SOURCE_NAME, "permissions": "0", "mentionable": False, "hoist": False})
            roles = request(http, "GET", f"/guilds/{guild}/roles", "WHOP_VERIFY_ROLES")
            source = next(r for r in roles if str(r["id"]) == str(source["id"]))
            bot_role = next(r for r in roles if str(r["id"]) == str(bot_role["id"]))
        else:
            source = sources[0]
        sid = str(source["id"])
        if source.get("managed") or int(source["permissions"]) or source.get("mentionable"):
            raise ValueError("Subscription source must have zero permissions")
        if sid in config.get("source_vip", []) or sid in config.get("paid_roles", {}).values():
            raise ValueError("Subscription source cannot replace an existing entitlement role")
        if sid == guild or not role_below(source, bot_role, guild):
            raise WhopSetupError("SOURCE_NOT_BELOW_WHOP")
        # Whop must stay below the community, derived access, staff and other
        # integration roles. No broad top-of-hierarchy placement is performed.
        if any(str(r["id"]) not in {guild, sid} and role_below(r, bot_role, guild) for r in roles):
            raise WhopSetupError("UNRELATED_ROLE_BELOW_WHOP")
        if any(str(p["id"]) == sid for c in channels for p in c.get("permission_overwrites", [])):
            raise ValueError("Subscription source must not have direct channel grants")
        aliases = config.get("subscription_sources", {})
        if sid in aliases and aliases[sid] != tier:
            raise ValueError("Existing subscription mapping requires explicit migration")
        if sid not in aliases:
            # Bounded read-only inventory; do not adopt a role already held by
            # members or infer that those members have paid subscriptions.
            after = "0"
            for _ in range(20):
                members = request(http, "GET", f"/guilds/{guild}/members?limit=1000&after={after}", "WHOP_MEMBERS")
                if any(sid in set(map(str, m.get("roles", []))) for m in members):
                    raise ValueError("Unmapped subscription role already has members")
                if len(members) < 1000:
                    break
                after = str(members[-1]["user"]["id"])
            else:
                raise ValueError("Member audit exceeds bound")
            if configuration(store) != config:
                raise RuntimeError("Rules configuration changed during setup")
            store.append("whop_setup_backup", guild, backup, backup_id)
            updated = {**config, "subscription_sources": {**aliases, sid: tier}}
            store.append("discord_rules_config", CONFIG_KEY, updated)
            if configuration(store) != updated:
                raise RuntimeError("Subscription mapping readback failed")
        result = {"status": "VERIFIED", "source_role": sid, "reference_role": tier,
                  "derived_role": config["paid_roles"][tier], "whop_bot_role": str(bot_role["id"]),
                  "members_changed": 0, "channels_changed": 0}
        store.append("whop_setup", guild, result, digest(["whop_setup", guild, result]))
        print("WHOP_SOURCE_SETUP " + json.dumps(result), flush=True)
        return result

"""Short-lived, read-only member access issued by the existing Discord bot.

No HTTP endpoint can mint an invitation. Bot issuance requires a fresh guild
membership check. Only token hashes are stored; tokens never grant scanner access.
"""

import hashlib
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
SESSION_SECONDS = 900
TICKET_SECONDS = 300


class MembershipUnavailable(RuntimeError):
    """Membership could not be verified; never serve protected data."""


def check_live_membership(principal, *, transport=None):
    """Recheck Discord on every protected request, including ticket exchange.

    No cached grant survives a removed role. Network/rate-limit failures fail
    closed. The bot credential is never sent to the browser or written to logs.
    """
    import httpx

    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "")
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "")
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "")
    roles = {
        r.strip() for r in os.getenv("JABBAZI_DISCORD_VIEWER_ROLE_IDS", "").split(",") if r.strip()
    }
    member = str(principal.get("member", ""))
    if (
        not guild.isdigit()
        or not owner.isdigit()
        or not token
        or any(not r.isdigit() or r == guild for r in roles)
    ):
        raise MembershipUnavailable("Membership verification is not configured")
    if str(principal.get("guild")) != guild or not member.isdigit():
        raise PermissionError("Member access denied")
    try:
        with httpx.Client(
            base_url="https://discord.com/api/v10", timeout=8, transport=transport
        ) as client:
            response = client.get(
                f"/guilds/{guild}/members/{member}", headers={"Authorization": "Bot " + token}
            )
        if response.status_code == 404:
            raise PermissionError("Member access removed")
        response.raise_for_status()
        current = response.json()
        if str(current.get("user", {}).get("id")) != member or current.get("pending", False):
            raise PermissionError("Member access denied")
        if member != owner and not roles.intersection(str(r) for r in current.get("roles", [])):
            raise PermissionError("VIP role required")
    except PermissionError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise MembershipUnavailable("Membership verification is temporarily unavailable") from None


def portal_origin():
    value = os.getenv("JABBAZI_MEMBER_ORIGIN", "https://jabbazi-research-api.onrender.com").rstrip(
        "/"
    )
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Member origin must be a canonical HTTPS origin")
    return value


def hashed(token):
    return hashlib.sha256(token.encode()).hexdigest()


def valid_principal(payload, now):
    """Fail closed on malformed, cross-guild or incorrectly scoped records."""
    try:
        expiry = datetime.fromisoformat(payload["expires_at"])
        configured_guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "")
        return (
            expiry.tzinfo is not None
            and expiry > now
            and payload.get("scope") == "sheets:read"
            and bool(payload.get("member"))
            and bool(payload.get("guild"))
            and (not configured_guild or str(payload["guild"]) == configured_guild)
        )
    except (ValueError, TypeError, KeyError):
        return False


def issue_ticket(store, *, guild, member, authorized, now=None):
    if not authorized:
        raise PermissionError("Member access denied")
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    key = hashed(token)
    store.append(
        "member_ticket",
        key,
        {
            "guild": str(guild),
            "member": str(member),
            "expires_at": (now + timedelta(seconds=TICKET_SECONDS)).isoformat(),
            "scope": "sheets:read",
        },
        key,
    )
    return token


def exchange_ticket(store, token, *, now=None):
    now = now or datetime.now(UTC)
    if not TOKEN_RE.fullmatch(token):
        raise PermissionError("Invalid member link")
    key = hashed(token)
    records = store.list_records("member_ticket", 1, entity=key)
    if not records or not valid_principal(records[0]["payload"], now):
        raise PermissionError("Member link expired")
    check_live_membership(records[0]["payload"])
    if not store.append("member_ticket_used", key, {}, hashed("member_ticket_used:" + key)):
        raise PermissionError("Member link already used")
    session = secrets.token_urlsafe(32)
    payload = {
        **records[0]["payload"],
        "expires_at": (now + timedelta(seconds=SESSION_SECONDS)).isoformat(),
    }
    store.append("member_session", hashed(session), payload, hashed(session))
    return session


def validate_session(store, token, *, now=None):
    now = now or datetime.now(UTC)
    if not token or not TOKEN_RE.fullmatch(token):
        raise PermissionError("Member sign-in required")
    key = hashed(token)
    records = store.list_records("member_session", 1, entity=key)
    if (
        not records
        or not valid_principal(records[0]["payload"], now)
        or store.list_records("member_session_revoked", 1, entity=key)
    ):
        raise PermissionError("Member session expired")
    check_live_membership(records[0]["payload"])
    return records[0]["payload"]

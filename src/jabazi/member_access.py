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
    if not records or datetime.fromisoformat(records[0]["payload"]["expires_at"]) <= now:
        raise PermissionError("Member link expired")
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
        or datetime.fromisoformat(records[0]["payload"]["expires_at"]) <= now
        or store.list_records("member_session_revoked", 1, entity=key)
    ):
        raise PermissionError("Member session expired")
    return records[0]["payload"]

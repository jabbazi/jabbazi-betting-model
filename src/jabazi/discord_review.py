"""Render/send experimental candidates to the owner's review channel only."""

import argparse
import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .automation import AutomaticScanner
from .config import Settings


def render(action, now=None):
    now = now or datetime.now(UTC)
    card = action.price
    if (
        card.starts_at is None
        or card.starts_at <= now
        or (now - card.source_timestamp).total_seconds() > 120
        or (now - card.source_timestamp).total_seconds() < 0
    ):
        return None
    if action.model_probability is None:
        return None
    line = "" if card.line is None else f" {card.line}"
    value = card.best_decimal
    american = (value - 1) * 100 if value >= 2 else -100 / (value - 1)
    fields = [
        {"name": "Selection", "value": f"{card.selection}{line}", "inline": True},
        {"name": "Market", "value": card.market, "inline": True},
        {
            "name": "Reference price",
            "value": f"{card.best_book}: {american:+.0f} ({value} decimal)",
        },
        {"name": "Research probability", "value": f"{action.model_probability:.1%}; unvalidated"},
        {"name": "Stake", "value": "None — research only"},
        {"name": "Price observed (UTC)", "value": card.source_timestamp.isoformat()},
        {"name": "Model decision", "value": action.reason},
    ]
    return {
        "username": "JABBAZI Research",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"RESEARCH / NOT A PICK — {card.event}"[:256],
                "color": 0x8B5CF6,
                "fields": fields,
                "footer": {"text": "Private review • no automatic VIP publication"},
                "timestamp": now.isoformat(),
            }
        ],
    }


def delivery_key(action):
    c = action.price
    parts = [
        c.sport,
        c.event_id,
        c.market,
        c.participant,
        c.selection,
        str(c.line),
        c.best_book,
        str(c.best_decimal),
        str(action.model_probability),
        action.model_version,
    ]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def webhook_request(url, payload=None):
    req = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Jabbazi/0.2"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def validate_webhook(url, channel):
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "discord.com"
        or not parsed.path.startswith("/api/webhooks/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an official Discord incoming webhook URL without query parameters")
    if not channel.isdigit():
        raise ValueError("JABBAZI_DISCORD_REVIEW_CHANNEL_ID is required")
    if str(webhook_request(url).get("channel_id")) != channel:
        raise ValueError("Webhook does not target the configured private review channel")
    if os.getenv("JABAZI_ENV") == "production":
        verify_private_channel(channel)


def verify_private_channel(channel, request=None):
    """Require owner-controlled guild and explicit private-channel overwrites.

    Discord server owners/administrators inherently bypass channel restrictions.
    No arbitrary role or member may receive an explicit view grant here.
    """
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "")
    guild = os.getenv("JABBAZI_DISCORD_GUILD_ID", "")
    owner = os.getenv("JABBAZI_DISCORD_OWNER_ID", "")
    analyst = os.getenv("JABBAZI_DISCORD_ANALYST_ROLE_ID", "")
    if not token or not all(x.isdigit() for x in (guild, owner, analyst, channel)):
        raise ValueError("Bot, guild, owner, analyst role and review channel are required")

    def get(path):
        req = urllib.request.Request(
            "https://discord.com/api/v10" + path,
            headers={"Authorization": "Bot " + token, "User-Agent": "Jabbazi/0.3"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)

    get = request or get
    info = get("/guilds/" + guild)
    if str(info["owner_id"]) != owner:
        raise ValueError("Configured Discord owner mismatch")
    bot = str(get("/users/@me")["id"])
    room = get("/channels/" + channel)
    if str(room.get("guild_id")) != guild or room.get("type") != 0:
        raise ValueError("Review target must be a guild text channel")
    view = 1 << 10
    permissions = room.get("permission_overwrites", [])
    everyone = [p for p in permissions if str(p["id"]) == guild and p["type"] == 0]
    if (
        len(everyone) != 1
        or not int(everyone[0]["deny"]) & view
        or int(everyone[0]["allow"]) & view
    ):
        raise ValueError("Review channel must deny public visibility")
    for entry in permissions:
        identity = (entry["type"], str(entry["id"]))
        if int(entry["allow"]) & view and identity not in {(0, analyst), (1, bot), (1, owner)}:
            raise ValueError("Unexpected role or member can view the review channel")
    return {"guild_id": guild, "channel_id": channel, "private_overwrites_verified": True}


def deliver_durable(action, url, store, channel):
    from .persistence.store import digest

    payload = render(action)
    if payload is None:
        return "skipped_stale_or_unmodeled"
    key = digest([channel, delivery_key(action)])
    claim = {"delivery_key": key, "channel_id": channel, "card_key": delivery_key(action)}
    if not store.append("delivery_claim", channel, claim, key):
        return "already_delivered_or_requires_review"
    try:
        response = webhook_request(url + "?wait=true", payload)
        message_id = str(response["id"])
    except Exception:
        store.append("delivery_result", key, {"status": "needs_review"}, digest([key, "result"]))
        raise RuntimeError("Discord delivery uncertain; inspect before retrying") from None
    store.append(
        "delivery_result",
        key,
        {"status": "delivered", "message_id": message_id},
        digest([key, "result"]),
    )
    return "delivered"


def deliver(action, url, database):
    platform_url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
    if platform_url:
        from .persistence.store import Store

        store = Store(platform_url)
        try:
            return deliver_durable(
                action, url, store, os.getenv("JABBAZI_DISCORD_REVIEW_CHANNEL_ID", "")
            )
        finally:
            store.close()
    if os.getenv("JABAZI_ENV") == "production":
        raise RuntimeError("Production Discord delivery requires the platform database")
    payload = render(action)
    if payload is None:
        return "skipped_stale_or_unmodeled"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS delivery (id TEXT PRIMARY KEY, status TEXT, message_id TEXT)"
        )
        key = delivery_key(action)
        # A reservation precedes the network call. Ambiguous failures are held
        # for inspection rather than silently duplicated on restart.
        try:
            db.execute("INSERT INTO delivery VALUES (?, ?, NULL)", (key, "reserved"))
            db.commit()
        except sqlite3.IntegrityError:
            return "already_delivered_or_requires_review"
        try:
            response = webhook_request(url + "?wait=true", payload)
            message = str(response["id"])
        except Exception:
            db.execute("UPDATE delivery SET status=? WHERE id=?", ("needs_review", key))
            db.commit()
            raise RuntimeError(
                "Discord delivery uncertain or rejected; inspect before retrying"
            ) from None
        db.execute(
            "UPDATE delivery SET status=?,message_id=? WHERE id=?", ("delivered", message, key)
        )
        return "delivered"


def main():
    parser = argparse.ArgumentParser(
        description="Preview research cards; --send posts to owner review only"
    )
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-credits", type=int, default=9)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error("--limit must be 1 through 10")
    settings = Settings.from_environment()
    url = os.getenv("JABBAZI_DISCORD_REVIEW_WEBHOOK", "")
    if args.send:
        validate_webhook(url, os.getenv("JABBAZI_DISCORD_REVIEW_CHANNEL_ID", ""))
    result = AutomaticScanner(
        settings, settings.database_path, max_credits_per_run=args.max_credits
    ).run("quick")
    candidates = [a for a in result.actions if render(a) is not None][: args.limit]
    if not args.send:
        print(
            json.dumps(
                {
                    "mode": "PREVIEW",
                    "cards": [render(a) for a in candidates],
                    "errors": result.errors,
                },
                indent=2,
            )
        )
        return
    if result.errors:
        raise SystemExit("Unhealthy scan; Discord delivery suppressed")
    for action in candidates:
        print(deliver(action, url, str(Path(settings.database_path).with_suffix(".delivery.db"))))


if __name__ == "__main__":
    main()

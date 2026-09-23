"""Owner-authorized learning-channel refresh; no role/permission changes.

Read-only unless --apply. Every publication is durably claimed before sending;
ambiguous sends require review instead of a duplicate retry.
"""

import argparse
import json
import os
from pathlib import Path
import re

from discord_setup import Discord
from jabazi.persistence.store import Store, digest

VERSION = "2026-09-23-v1"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def run(client, guild, owner, store, apply=False):
    info = client.request("GET", f"/guilds/{guild}")
    if str(info["owner_id"]) != str(owner):
        raise ValueError("Server owner mismatch")
    channels = client.request("GET", f"/guilds/{guild}/channels")
    targets = [
        c
        for c in channels
        if c["type"] == 0 and slug(c["name"]) in {"betting-basics", "learn-how-to"}
    ]
    if len(targets) != 1:
        raise ValueError("A unique betting-basics or learn-how-to text channel is required")
    target = targets[0]
    lessons = json.loads(
        Path(__file__).resolve().parents[1].joinpath("docs/discord/learn-how-to.json").read_text()
    )
    official = [
        c
        for c in channels
        if c["type"] == 0 and slug(c["name"]) in {"jabbazi-picks", "jabazi-picks", "vip-picks"}
    ]
    if official:
        lessons[0]["body"] += "\n\nOfficial picks: " + " · ".join(f"<#{c['id']}>" for c in official)
    contents = [f"**JABBAZI LEARN HOW TO | {x['title']}**\n\n{x['body']}" for x in lessons]
    if any(len(c) > 2000 for c in contents):
        raise ValueError("Lesson exceeds Discord message limit")
    if not apply:
        return {
            "channel_id": target["id"],
            "current_name": target["name"],
            "new_name": "📚｜learn-how-to",
            "lessons": len(contents),
            "mode": "preview",
        }
    if store is None or not store.ready():
        raise ValueError("Durable publication audit store required")
    client.request(
        "PATCH",
        f"/channels/{target['id']}",
        {
            "name": "📚｜learn-how-to",
            "topic": "Start here to learn how to place bets, use your own units, read odds and picks, understand markets, and manage risk. Educational examples; no guaranteed wins. Read lessons in order.",
        },
    )
    published, existing = [], []
    for index, content in enumerate(contents):
        key = digest(["discord_learning", guild, target["id"], VERSION, index])
        if not store.append(
            "learning_delivery_claim",
            key,
            {"channel": target["id"], "lesson": index, "content_hash": digest(content)},
            key,
        ):
            prior = store.list_records("learning_delivery_result", 1, entity=key)
            if not prior or prior[0]["payload"].get("status") != "delivered":
                raise RuntimeError(
                    f"Lesson {index} has an uncertain prior delivery; review before retry"
                )
            existing.append(prior[0]["payload"]["message_id"])
            continue
        try:
            message = client.request(
                "POST",
                f"/channels/{target['id']}/messages",
                {"content": content, "allowed_mentions": {"parse": []}},
            )
        except Exception:
            store.append("learning_delivery_result", key, {"status": "needs_review"})
            raise RuntimeError(f"Lesson {index} delivery needs review") from None
        store.append(
            "learning_delivery_result",
            key,
            {"status": "delivered", "message_id": str(message["id"])},
        )
        published.append(str(message["id"]))
    return {
        "channel_id": target["id"],
        "name": "📚｜learn-how-to",
        "published": len(published),
        "already_delivered": len(existing),
        "message_ids": published + existing,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("JABBAZI_DISCORD_BOT_TOKEN", "")
    guild = os.environ.get("JABBAZI_DISCORD_GUILD_ID", "")
    owner = os.environ.get("JABBAZI_DISCORD_OWNER_ID", "")
    if not token or not guild.isdigit() or not owner.isdigit():
        raise SystemExit(
            "Discord service credentials and verified owner configuration are required"
        )
    store = Store(os.environ["JABBAZI_PLATFORM_DATABASE_URL"]) if args.apply else None
    try:
        print(json.dumps(run(Discord(token), guild, owner, store, args.apply)))
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    main()

"""Bounded, deduplicated delivery of owner-issued records, never scanner promotion."""

import asyncio
import os
from datetime import datetime

from .official import all_cards, sync_ledger_results
from .persistence.store import digest


def channels():
    keys = {"main": "MAIN_CARD", "sprinkle": "SPRINKLES", "updates": "PICK_UPDATES"}
    values = {
        kind: os.getenv("JABBAZI_DISCORD_" + name + "_CHANNEL_ID", "")
        for kind, name in keys.items()
    }
    if not any(values.values()):
        return {}
    if (
        not all(v.isdigit() and int(v) > 0 for v in values.values())
        or len(set(values.values())) != 3
    ):
        raise ValueError("Configure three distinct official channels")
    return {k: int(v) for k, v in values.items()}


def embed_for(card):
    import discord
    from .sheet_images import odds

    def safe(text, maximum=1000):
        return discord.utils.escape_markdown(str(text))[:maximum]

    status = card["status"].replace("_", " ")
    embed = discord.Embed(
        title=("MAIN CARD" if card["card"] == "main" else "SPRINKLE") + " · " + status,
        colour=0x8B35E8,
        timestamp=datetime.fromisoformat(card["issued_at"]),
    )
    embed.description = (
        safe(card["event"])
        + "\n**"
        + safe(card["selection"])
        + ((" " + safe(card["line"])) if card["line"] is not None else "")
        + "**"
    )
    embed.add_field(
        name="Published price",
        value=safe(odds(card["decimal_odds"])) + " · " + safe(card["sportsbook"]),
        inline=True,
    )
    embed.add_field(
        name="Stake", value=card["stake_units"] + "u · $" + card["stake_dollars"], inline=True
    )
    embed.add_field(name="Play to", value=odds(card["minimum_decimal"]) + " or better", inline=True)
    embed.add_field(name="Reasoning", value=safe(card["reasoning"]), inline=False)
    embed.add_field(name="Risks / invalidation", value=safe(card["risks"]), inline=False)
    embed.add_field(
        name="Price observed",
        value=safe(card["price_observed_at"])
        + "\nThis is a snapshot. Verify the current line before acting.",
        inline=False,
    )
    if card["status"] == "PRICE_EXPIRED":
        embed.add_field(
            name="Price expired",
            value="Original card retained. This quote is not currently verified.",
            inline=False,
        )
    if card.get("reason"):
        embed.add_field(name="Update", value=safe(card["reason"]), inline=False)
    if card["withdrawn"]:
        embed.add_field(
            name="Withdrawal",
            value="Withdrawn after publication. Kept in the complete record.",
            inline=False,
        )
    if card["result"]:
        embed.add_field(
            name="Recorded result",
            value=card["result"].upper()
            + " · "
            + card["profit_units"]
            + "u · "
            + card["result_source"],
            inline=False,
        )
    if card.get("correction_reason"):
        embed.add_field(name="Correction", value=safe(card["correction_reason"]), inline=False)
    embed.set_footer(
        text=card["id"]
        + " · Revision "
        + str(card["revision"])
        + " · Owner-issued; model approval unchanged"
    )
    return embed


async def publish_official_once(client, store, config):
    import discord

    destinations = channels()
    if not destinations:
        return
    await asyncio.to_thread(sync_ledger_results, store)
    cards = await asyncio.to_thread(all_cards, store)
    delivered = 0
    for card in reversed(cards):
        channel_id = destinations[card["card"] if card["revision"] == 1 else "updates"]
        key = digest(["official_delivery", config.guild, card["id"], card["revision"], channel_id])
        # A prior claim includes ambiguous failures; do not repeat a potentially sent message.
        if await asyncio.to_thread(store.list_records, "official_delivery_claim", 1, entity=key):
            continue
        channel = await client.checked_channel(channel_id)
        if not await asyncio.to_thread(
            store.append,
            "official_delivery_claim",
            key,
            {"pick_id": card["id"], "revision": card["revision"], "channel": str(channel_id)},
            key,
        ):
            continue
        try:
            message = await channel.send(
                embed=embed_for(card), allowed_mentions=discord.AllowedMentions.none()
            )
            result = {"status": "delivered", "message_id": str(message.id)}
        except Exception:  # SDK exceptions can contain credentials; never log them.
            result = {"status": "needs_review"}
        await asyncio.to_thread(
            store.append, "official_delivery_result", key, result, digest([key, "result"])
        )
        delivered += 1
        if delivered >= 5:
            break

"""Opt-in Discord gateway process for private research tools, not official picks.

Run separately with ``python -m jabazi.discord_bot`` after reviewing permissions.
No token, user message content, or provider exception text is logged.
"""

import asyncio
import io
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from .discord_sheets import SPORTS, latest_sheet, parse_command, scanner_status
from .persistence.store import Store, digest
from .sheet_images import GROUPS, render_card


@dataclass(frozen=True)
class BotConfig:
    guild: int
    owner: int
    status_channel: int
    sheets_channel: int
    viewer_roles: frozenset[int]
    brand_channels: frozenset[int] = frozenset()
    brand_gif_url: str = ""

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.getenv("JABBAZI_DISCORD_" + name, "")
            if not value.isdigit() or int(value) <= 0:
                raise ValueError("Missing Discord configuration: " + name)
            return int(value)

        roles = os.getenv("JABBAZI_DISCORD_VIEWER_ROLE_IDS", "").split(",")
        roles = frozenset(int(r.strip()) for r in roles if r.strip())
        result = cls(
            required("GUILD_ID"),
            required("OWNER_ID"),
            required("STATUS_CHANNEL_ID"),
            required("SHEETS_CHANNEL_ID"),
            roles,
            frozenset(
                int(c.strip())
                for c in os.getenv("JABBAZI_DISCORD_BRAND_CHANNEL_IDS", "").split(",")
                if c.strip()
            ),
            os.getenv("JABBAZI_DISCORD_BRAND_GIF_URL", ""),
        )
        if result.status_channel == result.sheets_channel:
            raise ValueError("Use separate status and sheet channels")
        return result


def brand_trigger(config, *, guild, channel, author, bot_author, content, mentioned_ids, bot_id):
    """Only the owner's explicit bot mention triggers branding, never a mass ping alone."""
    url = urlparse(config.brand_gif_url)
    valid_asset = (
        url.scheme == "https"
        and url.hostname in {"cdn.discordapp.com", "media.discordapp.net"}
        and url.path.lower().endswith(".gif")
        and not url.username
        and not url.password
    )
    return bool(
        valid_asset
        and guild == config.guild
        and channel in config.brand_channels
        and author == config.owner
        and not bot_author
        and (bot_id in mentioned_ids or content.strip().lower() == "!guru")
    )


def validate_target(document, config, bot_id, bot_role_ids=()):
    """Fail closed on wrong guild, public target, or unreviewed explicit grants."""
    if int(document.get("guild_id", 0)) != config.guild or document.get("type") != 0:
        raise ValueError("Research target must be a text channel in the configured guild")
    if int(document["id"]) not in (config.status_channel, config.sheets_channel):
        raise ValueError("Target is not an approved research channel")
    view = 1 << 10
    entries = document.get("permission_overwrites", [])
    public = [p for p in entries if int(p["id"]) == config.guild and p["type"] == 0]
    if len(public) != 1 or not int(public[0]["deny"]) & view or int(public[0]["allow"]) & view:
        raise ValueError("Research channels must explicitly deny public visibility")
    allowed = {(1, config.owner), (1, bot_id)} | {
        (0, r) for r in config.viewer_roles | frozenset(bot_role_ids)
    }
    for p in entries:
        if int(p["allow"]) & view and (p["type"], int(p["id"])) not in allowed:
            raise ValueError("Unreviewed research channel access")


def command_allowed(config, *, guild, channel, bot_author, content):
    if bot_author or guild != config.guild:
        return None
    parsed = parse_command(content)
    if not parsed:
        return None
    destination = config.status_channel if parsed[0] == "status" else config.sheets_channel
    return parsed if channel == destination else None


def build_client(config, store):
    import discord
    import httpx

    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True

    class ResearchClient(discord.Client):
        async def on_ready(self):
            # Owner-requested branding: only the configured server's displayed icon.
            try:
                guild = await self.fetch_guild(config.guild)
                if guild.owner_id != config.owner or not guild.icon:
                    return
                key = digest(["discord_avatar", config.guild, guild.icon.key])
                records = await asyncio.to_thread(store.list_records, "discord_avatar", 1)
                if records and records[0]["entity"] == key:
                    return
                await self.user.edit(avatar=await guild.icon.read())
                await asyncio.to_thread(store.append, "discord_avatar", key, {"synced": True})
                print("DISCORD_AVATAR_SYNCED", flush=True)
            except Exception:  # noqa: BLE001 -- never log credential-bearing SDK errors
                print("DISCORD_AVATAR_UNAVAILABLE", flush=True)

        async def setup_hook(self):
            self.publisher = asyncio.create_task(self.publish_loop())

        async def checked_channel(self, channel_id):
            # Fetch current permissions rather than trusting an old gateway cache.
            token = os.environ["JABBAZI_DISCORD_BOT_TOKEN"]
            async with httpx.AsyncClient(
                base_url="https://discord.com/api/v10",
                headers={"Authorization": "Bot " + token},
                timeout=15,
            ) as http:

                async def get(path):
                    response = await http.get(path)
                    response.raise_for_status()
                    return response.json()

                guild = await get(f"/guilds/{config.guild}")
                if int(guild["owner_id"]) != config.owner:
                    raise ValueError("Server owner mismatch")
                member = await get(f"/guilds/{config.guild}/members/{self.user.id}")
                document = await get(f"/channels/{channel_id}")
                validate_target(
                    document, config, self.user.id, (int(r) for r in member.get("roles", []))
                )
            channel = await self.fetch_channel(channel_id)
            return channel

        async def send_sheets(self, channel, record, sports, page=1):
            if record is None:
                return await channel.send("CHEAT SHEETS UNAVAILABLE — no recent completed scan.")
            payload = record["payload"]
            if not payload["healthy"]:
                return await channel.send(
                    "DATA UNHEALTHY — latest scan failed checks. "
                    "No research sheets published for this scan."
                )
            files, embeds = [], []
            for sport in sports:
                for group, label in enumerate(GROUPS[sport]):
                    data = await asyncio.to_thread(render_card, record, sport, group, page=page)
                    if len(data) > 7_000_000:
                        raise ValueError("Image exceeds safe attachment size")
                    filename = f"jabbazi-{sport}-{group + 1}-page-{page}.png"
                    files.append(discord.File(io.BytesIO(data), filename=filename))
                    embed = discord.Embed(title=f"{sport.upper()} • {label}", colour=0x8B35E8)
                    embed.set_image(url=f"attachment://{filename}")
                    embeds.append(embed)
            text = (
                f"**JABBAZI RESEARCH SHEETS — NOT OFFICIAL PICKS**\n"
                f"Scan UTC: {payload['completed_at']}\n{payload['notice']}\n"
                "Tap an image to open it. Each sport has three market cards. "
                "More rows: `!cheatsheets nfl 2` (also mlb/cfb). "
                "Unavailable markets are labeled, never filled with invented percentages."
            )
            if payload["truncated"]:
                text += "\nRow limit reached: this export is incomplete."
            return await channel.send(text, files=files, embeds=embeds)

        async def on_message(self, message):
            if brand_trigger(
                config,
                guild=message.guild.id if message.guild else None,
                channel=message.channel.id,
                author=message.author.id,
                bot_author=message.author.bot or bool(message.webhook_id),
                content=message.content,
                mentioned_ids={user.id for user in message.mentions},
                bot_id=self.user.id,
            ):
                try:
                    key = digest(["discord_brand", config.guild, message.id])
                    if await asyncio.to_thread(store.append, "brand_delivery_claim", key, {}, key):
                        embed = discord.Embed(title="JABBAZI GURU", colour=0x8B35E8)
                        embed.set_image(url=config.brand_gif_url)
                        await message.channel.send(
                            embed=embed, allowed_mentions=discord.AllowedMentions.none()
                        )
                except Exception:  # noqa: BLE001 -- keep credentials out of SDK errors
                    print("DISCORD_BRAND_UNAVAILABLE", flush=True)
                return
            command = command_allowed(
                config,
                guild=message.guild.id if message.guild else None,
                channel=message.channel.id,
                bot_author=message.author.bot or bool(message.webhook_id),
                content=message.content,
            )
            if command is None:
                return
            try:
                channel = await self.checked_channel(message.channel.id)
                # One command response per channel per 30 seconds, across replicas.
                key = digest(["discord_command", channel.id, int(time.time()) // 30])
                claimed = await asyncio.to_thread(
                    store.append,
                    "discord_command_claim",
                    str(channel.id),
                    {"kind": command[0]},
                    key,
                )
                if not claimed:
                    return
                if command[0] == "status":
                    await channel.send(await asyncio.to_thread(scanner_status, store))
                else:
                    await self.send_sheets(
                        channel,
                        await asyncio.to_thread(latest_sheet, store),
                        command[1],
                        page=command[2] if len(command) == 3 else 1,
                    )
            except Exception:  # noqa: BLE001 -- do not expose credentials through SDK errors
                print("DISCORD_COMMAND_UNAVAILABLE", flush=True)

        async def publish_once(self):
            record = await asyncio.to_thread(latest_sheet, store)
            if record is None:
                return
            channel = await self.checked_channel(config.sheets_channel)
            key = digest(["discord_sheet", config.guild, channel.id, record["id"]])
            claim = {"sheet_id": record["id"], "channel": str(channel.id)}
            if not await asyncio.to_thread(store.append, "sheet_delivery_claim", key, claim, key):
                return
            # Claim before sending: ambiguous network failures require manual review,
            # never automatic duplicate publications.
            try:
                message = await self.send_sheets(channel, record, tuple(SPORTS))
                result = {"status": "delivered", "message_id": str(message.id)}
            except Exception:  # noqa: BLE001 -- uncertain delivery must be audited, not retried
                result = {"status": "needs_review"}
            await asyncio.to_thread(
                store.append, "sheet_delivery_result", key, result, digest([key, "result"])
            )

        async def publish_loop(self):
            await self.wait_until_ready()
            while not self.is_closed():
                try:
                    await self.publish_once()
                except Exception:  # noqa: BLE001 -- isolate delivery from scanner, redact errors
                    print("DISCORD_SHEET_UNAVAILABLE", flush=True)
                await asyncio.sleep(60)

        async def close(self):
            task = getattr(self, "publisher", None)
            if task:
                task.cancel()
            await super().close()

    return ResearchClient(
        intents=intents, allowed_mentions=discord.AllowedMentions.none(), max_messages=None
    )


def main():
    if os.getenv("JABBAZI_DISCORD_COMMANDS_ENABLED", "false").lower() != "true":
        raise SystemExit("Discord commands are disabled")
    config = BotConfig.from_env()
    token = os.getenv("JABBAZI_DISCORD_BOT_TOKEN", "")
    url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
    if not token or not url:
        raise SystemExit("Discord bot token and database URL are required")
    store = Store(url)
    try:
        if not store.ready():
            raise SystemExit("Database migration required")
        build_client(config, store).run(token, log_handler=None)
    finally:
        store.close()


if __name__ == "__main__":
    main()

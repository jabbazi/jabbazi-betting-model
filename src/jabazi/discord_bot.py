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

from .discord_sheets import SPORTS, latest_sheet, parse_command
from .discord_daily import daily_moneyline, render_text as render_daily_moneyline
from .persistence.store import Store, digest
from .sheet_images import render_card, page_count


@dataclass(frozen=True)
class BotConfig:
    guild: int
    owner: int
    status_channel: int
    sheets_channel: int
    viewer_roles: frozenset[int]
    brand_channels: frozenset[int] = frozenset()
    brand_gif_url: str = ""
    vip_role: int = 0
    main_card_channel: int = 0
    best_two_channel: int = 0
    results_channel: int = 0
    support_channel: int = 0

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
            guild=required("GUILD_ID"),
            owner=required("OWNER_ID"),
            status_channel=required("STATUS_CHANNEL_ID"),
            sheets_channel=required("SHEETS_CHANNEL_ID"),
            viewer_roles=roles,
            brand_channels=frozenset(
                int(channel.strip())
                for channel in os.getenv("JABBAZI_DISCORD_BRAND_CHANNEL_IDS", "").split(",")
                if channel.strip()
            ),
            brand_gif_url=os.getenv("JABBAZI_DISCORD_BRAND_GIF_URL", ""),
            vip_role=int(os.getenv("JABBAZI_DISCORD_VIP_ROLE_ID", "0") or 0),
            main_card_channel=int(
                os.getenv("JABBAZI_DISCORD_MAIN_CARD_CHANNEL_ID", "0") or 0
            ),
            best_two_channel=int(
                os.getenv("JABBAZI_DISCORD_BEST_TWO_CHANNEL_ID", "0") or 0
            ),
            results_channel=int(
                os.getenv("JABBAZI_DISCORD_RESULTS_CHANNEL_ID", "0") or 0
            ),
            support_channel=int(
                os.getenv("JABBAZI_DISCORD_SUPPORT_CHANNEL_ID", "0") or 0
            ),
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
    approved = {
        config.status_channel, config.sheets_channel, config.main_card_channel,
        config.best_two_channel, config.results_channel,
    } - {0}
    if int(document["id"]) not in approved:
        raise ValueError("Target is not an approved JABBAZI channel")
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
    if parsed[0] == "status":
        # !vip opens a read-only member app; it never invokes the owner scanner.
        return "portal", ()
    destination = config.sheets_channel
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
                await asyncio.to_thread(
                    store.append,
                    "member_brand",
                    "server",
                    {"icon_url": str(guild.icon.url)},
                    digest(["member_brand", config.guild, guild.icon.key]),
                )
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
            self.tree = discord.app_commands.CommandTree(self)

            @self.tree.command(name="cheatsheet", description="Show today's frozen 9 AM JABBAZI moneyline sheet")
            async def cheatsheet(interaction: discord.Interaction):
                if interaction.guild_id != config.guild:
                    return await interaction.response.send_message(
                        "This command is only available in the JABBAZI server.", ephemeral=True
                    )
                record = await asyncio.to_thread(daily_moneyline, store)
                await interaction.response.send_message(
                    render_daily_moneyline(record),
                    ephemeral=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )

            alert_roles = (
                "NFL Alerts", "CFB Alerts", "MLB Alerts", "NBA Alerts", "NHL Alerts",
                "Parlay Alerts", "Main Card Alerts", "Promo Alerts", "Cheat Sheet Alerts",
            )

            class AlertSelect(discord.ui.Select):
                def __init__(self):
                    super().__init__(
                        placeholder="Choose the alerts you want",
                        min_values=0,
                        max_values=len(alert_roles),
                        options=[discord.SelectOption(label=name, value=name) for name in alert_roles],
                    )

                async def callback(self, interaction: discord.Interaction):
                    if interaction.guild_id != config.guild:
                        return await interaction.response.send_message(
                            "Alert roles are only available in the JABBAZI server.",
                            ephemeral=True,
                        )
                    guild = interaction.guild
                    available = {role.name: role for role in guild.roles if role.name in alert_roles}
                    selected = set(self.values)
                    add = [available[name] for name in selected if name in available]
                    remove = [
                        role for role in interaction.user.roles
                        if role.name in alert_roles and role.name not in selected
                    ]
                    if add:
                        await interaction.user.add_roles(*add, reason="JABBAZI alert preference")
                    if remove:
                        await interaction.user.remove_roles(
                            *remove, reason="JABBAZI alert preference"
                        )
                    await interaction.response.send_message(
                        "Alert preferences updated.", ephemeral=True
                    )

            class AlertView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=180)
                    self.add_item(AlertSelect())

            @self.tree.command(name="alerts", description="Choose your JABBAZI sport and pick alerts")
            async def alerts(interaction: discord.Interaction):
                await interaction.response.send_message(
                    "Choose the alerts you want. You can change these anytime.",
                    view=AlertView(),
                    ephemeral=True,
                )

            @self.tree.command(name="support", description="Open a private JABBAZI support thread")
            async def support(interaction: discord.Interaction):
                if interaction.guild_id != config.guild or not config.support_channel:
                    return await interaction.response.send_message(
                        "Private support is not configured yet.", ephemeral=True
                    )
                channel = await self.fetch_channel(config.support_channel)
                if getattr(channel, "guild", None) is None or channel.guild.id != config.guild:
                    return await interaction.response.send_message(
                        "Support configuration is unavailable.", ephemeral=True
                    )
                thread = await channel.create_thread(
                    name=f"support-{interaction.user.id}",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    reason="JABBAZI member support request",
                )
                await thread.add_user(interaction.user)
                await thread.send(
                    "Tell us what you need help with. Never post passwords, sportsbook logins, "
                    "payment card numbers, or other secrets here.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await interaction.response.send_message(
                    f"Private support opened: {thread.mention}", ephemeral=True
                )

            @self.tree.command(name="vip", description="Open your private JABBAZI VIP member app")
            async def vip(interaction: discord.Interaction):
                if interaction.guild_id != config.guild:
                    return await interaction.response.send_message(
                        "This command is only available in the JABBAZI server.", ephemeral=True
                    )
                member = interaction.user
                role_ids = {role.id for role in getattr(member, "roles", [])}
                allowed = member.id == config.owner or bool(role_ids & config.viewer_roles)
                if not allowed:
                    return await interaction.response.send_message(
                        "VIP access is not active on your account. Use #upgrade-to-vip or contact support.",
                        ephemeral=True,
                    )
                from .member_access import issue_ticket, portal_origin
                ticket = await asyncio.to_thread(
                    issue_ticket, store, guild=config.guild, member=member.id, authorized=True
                )
                link = portal_origin() + "/vip#access=" + ticket
                await interaction.response.send_message(
                    f"Your private JABBAZI member link (expires quickly): {link}",
                    ephemeral=True,
                )

            await self.tree.sync(guild=discord.Object(id=config.guild))
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

        async def checked_public_channel(self, channel_id):
            token = os.environ["JABBAZI_DISCORD_BOT_TOKEN"]
            async with httpx.AsyncClient(
                base_url="https://discord.com/api/v10",
                headers={"Authorization": "Bot " + token},
                timeout=15,
            ) as http:
                guild = (await http.get(f"/guilds/{config.guild}")).json()
                if int(guild["owner_id"]) != config.owner:
                    raise ValueError("Server owner mismatch")
                response = await http.get(f"/channels/{channel_id}")
                response.raise_for_status()
                document = response.json()
                if int(document.get("guild_id", 0)) != config.guild or document.get("type") != 0:
                    raise ValueError("Public target must be configured guild text channel")
                view = 1 << 10
                everyone = [
                    p for p in document.get("permission_overwrites", [])
                    if int(p["id"]) == config.guild and p["type"] == 0
                ]
                if (
                    len(everyone) != 1
                    or int(everyone[0]["deny"]) & view
                    or not int(everyone[0]["allow"]) & view
                ):
                    raise ValueError("Results channel must explicitly allow public visibility")
            return await self.fetch_channel(channel_id)

        async def send_sheets(self, channel, record, sports, page=None):
            if record is None:
                return await channel.send("CHEAT SHEETS UNAVAILABLE — no recent completed scan.")
            payload = record["payload"]
            if not payload["healthy"]:
                return await channel.send(
                    "DATA UNHEALTHY — latest scan failed checks. "
                    "No research sheets published for this scan."
                )
            last_message = None
            for sport in sports:
                files = []
                for group in range(3):
                    pages = (
                        [page]
                        if page is not None
                        else range(1, page_count(record, sport, group) + 1)
                    )
                    for number in pages:
                        data = await asyncio.to_thread(
                            render_card, record, sport, group, page=number
                        )
                        if len(data) > 7_000_000:
                            raise ValueError("Image exceeds safe attachment size")
                        filename = f"jabbazi-{sport}-{group + 1}-page-{number}.png"
                        files.append(discord.File(io.BytesIO(data), filename=filename))
                        if len(files) == 10:
                            last_message = await channel.send(files=files)
                            files = []
                if files:
                    last_message = await channel.send(files=files)
            return last_message

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
                if command[0] == "portal":
                    await self.checked_channel(config.sheets_channel)
                    # Check current membership over REST, not just a cached message role.
                    member = await message.guild.fetch_member(message.author.id)
                    allowed = member.id == config.owner or bool(
                        {r.id for r in member.roles} & config.viewer_roles
                    )
                    if not allowed:
                        await message.channel.send(
                            "The JABBAZI member app requires an approved VIP role.",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        return
                    key = digest(
                        ["member_access_command", config.guild, member.id, int(time.time()) // 30]
                    )
                    if not await asyncio.to_thread(
                        store.append, "member_access_command", str(member.id), {}, key
                    ):
                        return
                    from .member_access import issue_ticket, portal_origin

                    ticket = await asyncio.to_thread(
                        issue_ticket,
                        store,
                        guild=config.guild,
                        member=member.id,
                        authorized=allowed,
                    )
                    link = portal_origin() + "/vip#access=" + ticket
                    embed = discord.Embed(
                        title="Open JABBAZI GURU",
                        url=link,
                        colour=0x8B35E8,
                        description="Your private research room: game sheets, player props, anytime TDs, insights and lessons. This single-use link expires in 5 minutes; access lasts 15 minutes. Keep this link private.",
                    )
                    try:
                        await member.send(
                            embed=embed, allowed_mentions=discord.AllowedMentions.none()
                        )
                        await message.channel.send(
                            "Your private JABBAZI app link is in your DMs.",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    except discord.Forbidden:
                        await message.channel.send(
                            "Enable direct messages from this server, then type !vip again for your private app link.",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    return
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
                await self.send_sheets(
                    channel,
                    await asyncio.to_thread(latest_sheet, store),
                    command[1],
                    page=command[2] if len(command) == 3 else None,
                )
            except Exception:  # noqa: BLE001 -- do not expose credentials through SDK errors
                print("DISCORD_COMMAND_UNAVAILABLE", flush=True)

        async def publish_status_once(self):
            channel = await self.checked_channel(config.status_channel)
            text = await asyncio.to_thread(__import__(
                "jabazi.discord_sheets", fromlist=["scanner_status"]
            ).scanner_status, store)
            key = digest(["discord_status", config.guild, text])
            if not await asyncio.to_thread(
                store.append, "discord_status_claim", str(channel.id), {"text": text}, key
            ):
                return
            from .discord_content import scanner_status_embed
            await channel.send(
                embed=discord.Embed.from_dict(scanner_status_embed(text)),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        async def publish_best_two_once(self):
            if not config.best_two_channel:
                return
            scans = await asyncio.to_thread(store.list_records, "scan_run", 5)
            candidate = None
            for row in scans:
                value = row["payload"].get("best_two_sheet_candidate")
                if value and value.get("legs"):
                    candidate = value
                    break
            if candidate is None:
                return
            from .discord_content import best_two_embed
            payload = best_two_embed(candidate)
            if payload is None:
                return
            key = digest(["discord_best_two", config.guild, candidate])
            if not await asyncio.to_thread(
                store.append, "discord_best_two_claim", str(config.best_two_channel), {}, key
            ):
                return
            channel = await self.checked_channel(config.best_two_channel)
            await channel.send(
                embed=discord.Embed.from_dict(payload),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        async def publish_official_picks_once(self):
            if not config.main_card_channel:
                return
            from .discord_content import official_pick_embed
            rows = await asyncio.to_thread(store.list_records, "candidate", 100)
            channel = await self.checked_channel(config.main_card_channel)
            for row in reversed(rows):
                payload = official_pick_embed(row["payload"])
                if payload is None:
                    continue
                price = row["payload"].get("price") or {}
                key = digest([
                    "discord_official_pick", config.guild,
                    price.get("event_id"), price.get("market"), price.get("participant"),
                    price.get("selection"), price.get("line"),
                    row["payload"].get("model_version"),
                ])
                if not await asyncio.to_thread(
                    store.append, "discord_official_pick_claim", str(channel.id), {}, key
                ):
                    continue
                await channel.send(
                    embed=discord.Embed.from_dict(payload),
                    allowed_mentions=discord.AllowedMentions.none(),
                )

        async def publish_results_once(self):
            if not config.results_channel:
                return
            from .performance import report as performance_report
            from .discord_content import performance_text
            report = await asyncio.to_thread(performance_report, store)
            text = performance_text(report)
            key = digest(["discord_results", config.guild, text])
            if not await asyncio.to_thread(
                store.append, "discord_results_claim", str(config.results_channel), {}, key
            ):
                return
            channel = await self.checked_public_channel(config.results_channel)
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())

        async def publish_once(self):
            """Legacy research-sheet publisher retained for explicit/manual use only."""
            record = await asyncio.to_thread(latest_sheet, store)
            if record is None:
                return
            channel = await self.checked_channel(config.sheets_channel)
            key = digest(["discord_sheet", config.guild, channel.id, record["id"], "legacy-v2"])
            claim = {"sheet_id": record["id"], "channel": str(channel.id)}
            if not await asyncio.to_thread(
                store.append, "sheet_delivery_claim", key, claim, key
            ):
                return
            try:
                message = await self.send_sheets(channel, record, tuple(SPORTS))
                result = {"status": "delivered", "message_id": str(message.id)}
            except Exception:
                result = {"status": "needs_review"}
            await asyncio.to_thread(
                store.append, "sheet_delivery_result", key, result, digest([key, "result"])
            )

        async def publish_daily_once(self):
            record = await asyncio.to_thread(daily_moneyline, store)
            if record is None:
                return
            channel = await self.checked_channel(config.sheets_channel)
            key = digest(["discord_daily_moneyline", config.guild, channel.id, record["id"]])
            claim = {"sheet_id": record["id"], "channel": str(channel.id)}
            if not await asyncio.to_thread(
                store.append, "daily_sheet_delivery_claim", key, claim, key
            ):
                return
            try:
                text = render_daily_moneyline(record)
                messages = []
                while text:
                    split = min(len(text), 1900)
                    if split < len(text):
                        newline = text.rfind("\n", 0, split)
                        if newline > 500:
                            split = newline
                    part, text = text[:split], text[split:].lstrip()
                    message = await channel.send(
                        part, allowed_mentions=discord.AllowedMentions.none()
                    )
                    messages.append(str(message.id))
                result = {"status": "delivered", "message_ids": messages}
            except Exception:  # noqa: BLE001 -- uncertain delivery must be audited, not retried
                result = {"status": "needs_review"}
            await asyncio.to_thread(
                store.append, "daily_sheet_delivery_result", key, result, digest([key, "result"])
            )

        async def publish_loop(self):
            await self.wait_until_ready()
            while not self.is_closed():
                try:
                    await self.publish_daily_once()
                    await self.publish_status_once()
                    await self.publish_best_two_once()
                    await self.publish_official_picks_once()
                    await self.publish_results_once()
                except Exception:  # noqa: BLE001 -- isolate delivery from scanner, redact errors
                    print("DISCORD_PUBLISH_UNAVAILABLE", flush=True)
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

"""Opt-in Discord gateway process for private research tools, not official picks.

Run separately with ``python -m jabazi.discord_bot`` after reviewing permissions.
No token, user message content, or provider exception text is logged.
"""

import asyncio
import io
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from urllib.parse import urlparse

from .discord_access import is_vip_name
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
    research_channel: int = 0
    market_channel: int = 0
    welcome_channel: int = 0
    guide_channel: int = 0
    access_channel: int = 0
    general_channel: int = 0
    bot_log_channel: int = 0
    members_enabled: bool = False

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.getenv("JABBAZI_DISCORD_" + name, "")
            if not value.isdigit() or int(value) <= 0:
                raise ValueError("Missing Discord configuration: " + name)
            return int(value)

        roles = os.getenv("JABBAZI_DISCORD_VIEWER_ROLE_IDS", "").split(",")
        roles.append(os.getenv("JABBAZI_DISCORD_BILLING_ROLE_ID", ""))
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
            research_channel=int(os.getenv("JABBAZI_DISCORD_VIP_RESEARCH_CHANNEL_ID", "0") or 0),
            market_channel=int(os.getenv("JABBAZI_DISCORD_MARKET_WATCH_CHANNEL_ID", "0") or 0),
            welcome_channel=int(os.getenv("JABBAZI_DISCORD_WELCOME_CHANNEL_ID", "0") or 0),
            guide_channel=int(os.getenv("JABBAZI_DISCORD_GUIDE_CHANNEL_ID", "0") or 0),
            access_channel=int(os.getenv("JABBAZI_DISCORD_ACCESS_CHANNEL_ID", "0") or 0),
            general_channel=int(os.getenv("JABBAZI_DISCORD_GENERAL_CHANNEL_ID", "0") or 0),
            bot_log_channel=int(os.getenv("JABBAZI_DISCORD_BOT_LOG_CHANNEL_ID", "0") or 0),
        )
        if result.status_channel == result.sheets_channel:
            raise ValueError("Use separate status and sheet channels")
        return result


def access_destination(config):
    return f"<#{config.access_channel}>" if config.access_channel else "Get Access"


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
        config.best_two_channel, config.results_channel, config.research_channel, config.market_channel,
    } - {0}
    if int(document["id"]) not in approved:
        raise ValueError("Target is not an approved JABBAZI channel")
    view = 1 << 10
    entries = document.get("permission_overwrites", [])
    public = [p for p in entries if int(p["id"]) == config.guild and p["type"] == 0]
    if len(public) != 1 or not int(public[0]["deny"]) & view or int(public[0]["allow"]) & view:
        raise ValueError("Research channels must explicitly deny public visibility")
    approved_roles = config.viewer_roles | frozenset(bot_role_ids)
    if config.vip_role:
        approved_roles = approved_roles | frozenset({config.vip_role})
    allowed = {(1, config.owner), (1, bot_id)} | {
        (0, role_id) for role_id in approved_roles
    }
    for p in entries:
        if int(p["allow"]) & view and (p["type"], int(p["id"])) not in allowed:
            raise ValueError("Unreviewed research channel access")



def member_has_vip(config, member):
    """Manual VIP-family roles and configured viewer roles grant member-app access."""
    role_ids = {
        int(role.id)
        for role in getattr(member, "roles", [])
        if getattr(role, "id", None) is not None
    }
    role_names = {
        str(getattr(role, "name", "")).strip().upper()
        for role in getattr(member, "roles", [])
        if str(getattr(role, "name", "")).strip()
    }
    configured = set(config.viewer_roles)
    if config.vip_role:
        configured.add(config.vip_role)
    return bool(
        int(getattr(member, "id", 0)) == config.owner
        or role_ids & configured
        or any(is_vip_name(name) for name in role_names)
    )

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
    intents.members = config.members_enabled

    class ResearchClient(discord.Client):
        async def on_member_join(self, member):
            from .discord_welcome import welcome_member
            try:
                await welcome_member(self, store, config, member)
            except Exception as exc:
                print(f"DISCORD_MEMBER_WELCOME_UNAVAILABLE_{type(exc).__name__}", flush=True)
                await self.log_operational_failure("member-welcome", exc)

        async def log_operational_failure(self, lane, exc):
            if not config.bot_log_channel:
                return
            try:
                channel = await self.fetch_channel(config.bot_log_channel)
                if channel.guild.id != config.guild or channel.permissions_for(channel.guild.default_role).view_channel:
                    return
                for role in channel.guild.roles:
                    if (is_vip_name(role.name) or role.id in config.viewer_roles or role.id == config.vip_role) and channel.permissions_for(role).view_channel:
                        return
                status = getattr(exc, "status", None)
                status = status if isinstance(status, int) else "unavailable"
                error = type(exc).__name__
                key = digest(["discord_ops_notice", lane, error, status, datetime.now(UTC).strftime("%Y-%m-%dT%H")])
                if not await asyncio.to_thread(store.append, "discord_ops_notice", lane, {"error": error, "http_status": status}, key):
                    return
                await channel.send(f"⚠️ **JABBAZI GURU · {lane}**\n{error} · HTTP {status}. Check the worker diagnostics for this operation.", allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                print("DISCORD_PRIVATE_DIAGNOSTIC_UNAVAILABLE", flush=True)

        async def on_guild_role_update(self, before, after):
            from .discord_migration import PIN_MESSAGES
            if after.guild.id != config.guild or before.permissions.value & PIN_MESSAGES or not after.permissions.value & PIN_MESSAGES:
                return
            if getattr(self, "_pin_refresh_running", False):
                return
            self._pin_refresh_running = True
            try:
                member = await after.guild.fetch_member(self.user.id)
                if after.id not in {role.id for role in member.roles}:
                    return
                result = await asyncio.to_thread(subprocess.run, [sys.executable, "tools/seed_discord_content.py", "--apply"], capture_output=True, text=True, timeout=300)
                for line in result.stdout.splitlines():
                    if line.startswith(("DISCORD_ONBOARDING_VERIFICATION ", "DISCORD_OPERATION_")):
                        print(line, flush=True)
                print("DISCORD_PIN_PERMISSION_REFRESH_" + ("VERIFIED" if result.returncode == 0 else "INCOMPLETE"), flush=True)
            except Exception as exc:
                print(f"DISCORD_PIN_PERMISSION_REFRESH_UNAVAILABLE_{type(exc).__name__}", flush=True)
            finally:
                self._pin_refresh_running = False

        async def on_ready(self):
            print(f"DISCORD_GATEWAY_READY MEMBERS_INTENT={config.members_enabled} WELCOME_CHANNEL={config.welcome_channel}", flush=True)
            if os.getenv("JABBAZI_DISCORD_COMPACT_MIGRATION_V1", "false").lower() == "true":
                try:
                    done = await asyncio.to_thread(
                        store.list_records, "discord_compact_migration", 1, entity="v1"
                    )
                    if not done:
                        result = await asyncio.to_thread(
                            subprocess.run,
                            [
                                sys.executable,
                                "tools/bootstrap_discord.py",
                                "--apply",
                                "--archive-obsolete",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=300,
                            check=False,
                        )
                        if result.returncode != 0:
                            detail = (result.stderr or result.stdout or "unknown").strip()
                            detail = detail.splitlines()[-1][:180] if detail else "unknown"
                            detail = detail.replace(os.getenv("JABBAZI_DISCORD_BOT_TOKEN", ""), "[redacted]")
                            print(
                                "DISCORD_COMPACT_MIGRATION_FAILED: " + detail,
                                flush=True,
                            )
                            raise RuntimeError("Discord compact migration failed")
                        await asyncio.to_thread(
                            store.append,
                            "discord_compact_migration",
                            "v1",
                            {"status": "APPLIED"},
                            digest(["discord_compact_migration", "v1"]),
                        )
                        print("DISCORD_COMPACT_MIGRATION_APPLIED", flush=True)
                except Exception:  # noqa: BLE001 -- never expose Discord credentials
                    print("DISCORD_COMPACT_MIGRATION_UNAVAILABLE", flush=True)

            # Owner-requested branding: only the configured server's displayed icon.
            try:
                guild = await self.fetch_guild(config.guild)
                if guild.owner_id != config.owner:
                    return
                if getattr(self.user, "name", "JABBAZI GURU") != "JABBAZI GURU":
                    await self.user.edit(username="JABBAZI GURU")
                if not guild.icon:
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

            @self.tree.error
            async def command_error(interaction, error):
                original = getattr(error, "original", error)
                print(f"DISCORD_SLASH_{type(original).__name__}_HTTP_{getattr(original, 'status', None)}", flush=True)
                sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
                try:
                    await sender("This action could not be completed. Please use /support or contact staff.", ephemeral=True)
                except discord.HTTPException as response_error:
                    print(f"DISCORD_SLASH_RESPONSE_HTTP_{response_error.status}_CODE_{response_error.code}", flush=True)

            @self.tree.command(name="cheatsheet", description="Show today's frozen 9 AM JABBAZI moneyline sheet")
            async def cheatsheet(interaction: discord.Interaction):
                if interaction.guild_id != config.guild:
                    return await interaction.response.send_message(
                        "This command is only available in the JABBAZI server.", ephemeral=True
                    )
                await interaction.response.defer(ephemeral=True)
                member = await interaction.guild.fetch_member(interaction.user.id)
                if not member_has_vip(config, member):
                    return await interaction.followup.send(
                        f"The daily sheet requires an approved VIP role. See {access_destination(config)}.",
                        ephemeral=True,
                    )
                record = await asyncio.to_thread(daily_moneyline, store)
                text = render_daily_moneyline(record)
                # Return exactly the stored snapshot; never scan or flood a public channel.
                if len(text) <= 1900:
                    await interaction.followup.send(text, ephemeral=True)
                else:
                    date = record["payload"]["date"]
                    await interaction.followup.send(
                        f"Today's frozen JABBAZI moneyline sheet • {date}",
                        file=discord.File(io.BytesIO(text.encode()), filename=f"jabbazi-{date}.txt"),
                        ephemeral=True,
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
                    await interaction.response.defer(ephemeral=True)
                    guild = interaction.guild
                    member = await guild.fetch_member(interaction.user.id)
                    available = {
                        role.name: role for role in guild.roles
                        if role.name in alert_roles and role.permissions.value == 0
                        and not role.managed and guild.me is not None
                        and role.position < guild.me.top_role.position
                        and sum(r.name == role.name for r in guild.roles) == 1
                    }
                    if set(self.values) - set(available):
                        return await interaction.followup.send(
                            "An alert role is missing or cannot safely be assigned. Please contact staff.", ephemeral=True
                        )
                    selected = set(self.values)
                    add = [available[name] for name in selected if name in available]
                    remove = [
                        role for role in member.roles
                        if role.name in available and role.name not in selected
                    ]
                    if add:
                        await member.add_roles(*add, reason="JABBAZI alert preference")
                    if remove:
                        await member.remove_roles(
                            *remove, reason="JABBAZI alert preference"
                        )
                    await interaction.followup.send(
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
            @discord.app_commands.choices(category=[
                discord.app_commands.Choice(name=name, value=name)
                for name in ("VIP access", "Billing", "Technical issue", "Other")
            ])
            async def support(interaction: discord.Interaction, category: str = "Other"):
                if interaction.guild_id != config.guild or not config.support_channel:
                    return await interaction.response.send_message(
                        "Private support is not configured yet.", ephemeral=True
                    )
                await interaction.response.defer(ephemeral=True)
                channel = await self.fetch_channel(config.support_channel)
                if getattr(channel, "guild", None) is None or channel.guild.id != config.guild:
                    return await interaction.followup.send(
                        "Support configuration is unavailable.", ephemeral=True
                    )
                thread = await channel.create_thread(
                    name=f"support-{category.lower().replace(' ', '-')}-{interaction.user.id}",
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
                await interaction.followup.send(
                    f"Private support opened: {thread.mention}", ephemeral=True
                )

            @self.tree.command(name="vip", description="Open your private JABBAZI VIP member app")
            async def vip(interaction: discord.Interaction):
                if interaction.guild_id != config.guild:
                    return await interaction.response.send_message(
                        "This command is only available in the JABBAZI server.", ephemeral=True
                    )
                await interaction.response.defer(ephemeral=True)
                member = await interaction.guild.fetch_member(interaction.user.id)
                allowed = member_has_vip(config, member)
                if not allowed:
                    return await interaction.followup.send(
                        f"VIP access requires an approved role. See {access_destination(config)} or use /support.",
                        ephemeral=True,
                    )
                from .member_access import issue_ticket, portal_origin
                ticket = await asyncio.to_thread(
                    issue_ticket, store, guild=config.guild, member=member.id, authorized=True
                )
                link = portal_origin() + "/vip#access=" + ticket
                await interaction.followup.send(
                    f"Your private JABBAZI member link (expires quickly): {link}",
                    ephemeral=True,
                )

            self.tree.copy_global_to(guild=discord.Object(id=config.guild))
            synced = await self.tree.sync(guild=discord.Object(id=config.guild))
            expected = {"vip", "cheatsheet", "alerts", "support"}
            if {command.name for command in synced} != expected:
                raise RuntimeError("Discord command registration mismatch")
            print("DISCORD_COMMANDS_REGISTERED: vip,cheatsheet,alerts,support", flush=True)
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
                guild_roles = await get(f"/guilds/{config.guild}/roles")
                vip_alias_ids = {
                    int(role["id"])
                    for role in guild_roles
                    if is_vip_name(role.get("name")) or role.get("name", "").upper() in {"JABBAZI TEAM", "MODERATOR"}
                }
                document = await get(f"/channels/{channel_id}")
                validate_target(
                    document,
                    config,
                    self.user.id,
                    tuple(int(r) for r in member.get("roles", [])) + tuple(vip_alias_ids),
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
                    # Current VIP-family role grants app access; billing is not required.
                    member = await message.guild.fetch_member(message.author.id)
                    allowed = member_has_vip(config, member)
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
                    except discord.Forbidden:
                        if config.support_channel:
                            support = await self.fetch_channel(config.support_channel)
                            if getattr(support, "guild", None) is None or support.guild.id != config.guild:
                                raise ValueError("Support channel guild mismatch")
                            thread = await support.create_thread(
                                name=f"vip-access-{member.id}",
                                type=discord.ChannelType.private_thread,
                                invitable=False,
                                reason="Private JABBAZI VIP app-link fallback",
                            )
                            await thread.add_user(member)
                            await thread.send(
                                embed=embed, allowed_mentions=discord.AllowedMentions.none()
                            )
                            await message.channel.send(
                                f"Your private VIP access thread is ready: {thread.mention}",
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                        else:
                            await message.channel.send(
                                "Your DMs are closed. Use /vip for a private in-app link.",
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                    else:
                        await message.channel.send(
                            "Your private JABBAZI app link is in your DMs.",
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
            from .discord_content import scanner_status_embed
            previous = await asyncio.to_thread(store.list_records, "discord_status_message", 1, entity=str(channel.id))
            prior = previous[0]["payload"] if previous else {}
            if prior.get("status") == "needs_review" or prior.get("text") == text:
                return
            embed = discord.Embed.from_dict(scanner_status_embed(text))
            if prior.get("message_id"):
                message = await channel.fetch_message(int(prior["message_id"]))
                await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            else:
                key = digest(["discord_status_panel", config.guild, channel.id])
                if not await asyncio.to_thread(store.append, "discord_status_claim", str(channel.id), {}, key):
                    return
                try:
                    message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    await asyncio.to_thread(store.append, "discord_status_message", str(channel.id), {"status": "needs_review"})
                    raise
            await asyncio.to_thread(store.append, "discord_status_message", str(channel.id),
                                    {"message_id": str(message.id), "text": text, "status": "delivered"})

        async def publish_best_two_once(self):
            if not config.best_two_channel:
                return
            scans = await asyncio.to_thread(store.list_records, "scan_run", 1)
            candidate = None
            for row in scans:
                payload = row["payload"]
                try:
                    at = datetime.fromisoformat(payload["completed_at"])
                    if not payload.get("healthy") or not 0 <= (datetime.now(UTC)-at).total_seconds() <= 900:
                        continue
                except (KeyError, ValueError, TypeError):
                    continue
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
            channel = await self.checked_channel(config.best_two_channel)
            legs = [[leg.get(field) for field in ("event", "market", "selection", "participant", "line")] for leg in candidate["legs"]]
            key = digest(["discord_best_two", config.guild, datetime.now(ZoneInfo("America/Chicago")).date().isoformat(), legs, candidate.get("status")])
            if not await asyncio.to_thread(
                store.append, "discord_best_two_claim", str(config.best_two_channel), {}, key
            ):
                return
            await channel.send(
                embed=discord.Embed.from_dict(payload),
                **self.alert_delivery("Parlay Alerts"),
            )

        async def publish_official_picks_once(self):
            if not config.main_card_channel:
                return
            from .discord_content import official_pick_embed
            rows = await asyncio.to_thread(store.list_records, "candidate", 100)
            channel = await self.checked_channel(config.main_card_channel)
            for row in reversed(rows):
                from .vip.data import paused
                from .discord_daily import sport_label
                if await asyncio.to_thread(paused, store, sport_label(row["payload"].get("price", {}).get("sport", ""))):
                    continue
                payload = official_pick_embed(row["payload"])
                if payload is None:
                    continue
                from .member_access import portal_origin
                payload["url"] = portal_origin() + "/vip#detail=" + row["id"]
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
                    **self.alert_delivery("Main Card Alerts", row["payload"].get("price", {}).get("sport")),
                )

        def alert_delivery(self, name, sport=None):
            from .discord_daily import sport_label
            names = {name}
            label = sport_label(sport) if sport else None
            if label in {"NFL", "CFB", "MLB", "NBA", "NHL"}:
                names.add(label + " Alerts")
            guild = self.get_guild(config.guild)
            roles = [] if guild is None else [role for role in guild.roles
                if role.name in names and role.permissions.value == 0 and not role.managed
                and guild.me is not None and role.position < guild.me.top_role.position
                and sum(other.name == role.name for other in guild.roles) == 1]
            return {"content": " ".join(role.mention for role in roles) or None,
                    "allowed_mentions": discord.AllowedMentions(everyone=False, users=False, roles=roles, replied_user=False)}

        async def publish_research_once(self):
            await self.publish_observations("research", config.research_channel)

        async def publish_market_once(self):
            await self.publish_observations("market", config.market_channel)

        async def publish_observations(self, lane, channel_id):
            if not channel_id:
                return
            from .discord_observations import observations
            snapshots = await asyncio.to_thread(store.list_records, "research_sheet", 2, entity="latest_scan")
            updates = observations(snapshots, lane=lane)
            if not updates:
                return
            channel = await self.checked_channel(channel_id)
            for update in updates:
                key = digest(["discord_observation", config.guild, lane, update["identity"]])
                if not await asyncio.to_thread(store.append, "discord_observation_claim", str(channel_id), {}, key):
                    continue
                await channel.send(embed=discord.Embed.from_dict(update["embed"]), allowed_mentions=discord.AllowedMentions.none())

        async def publish_results_once(self):
            if not config.results_channel:
                return
            from .performance import report as performance_report
            from .discord_content import performance_text
            report = await asyncio.to_thread(performance_report, store)
            text = performance_text(report)
            channel = await self.checked_public_channel(config.results_channel)
            key = digest(["discord_results", config.guild, text])
            if not await asyncio.to_thread(
                store.append, "discord_results_claim", str(config.results_channel), {}, key
            ):
                return
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
                if len(text) <= 1900:
                    delivery = self.alert_delivery("Cheat Sheet Alerts")
                    prefix = delivery.pop("content") or ""
                    message = await channel.send((prefix+"\n"+text).strip(), **delivery)
                else:
                    date = record["payload"]["date"]
                    delivery = self.alert_delivery("Cheat Sheet Alerts")
                    prefix = delivery.pop("content") or ""
                    message = await channel.send(
                        (prefix+"\n" if prefix else "") +
                        f"🟣 **JABBAZI GURU DAILY MONEYLINE CHEAT SHEET • {date}**\n"
                        f"{record['payload']['row_count']} games • Frozen snapshot • Full slate attached.\n"
                        "Research leans are not automatically official wagers. Use /cheatsheet to retrieve this same sheet.",
                        file=discord.File(io.BytesIO(text.encode()), filename=f"jabbazi-{date}.txt"),
                        **delivery,
                    )
                result = {"status": "delivered", "message_ids": [str(message.id)]}
            except Exception:  # noqa: BLE001 -- uncertain delivery must be audited, not retried
                result = {"status": "needs_review"}
            await asyncio.to_thread(
                store.append, "daily_sheet_delivery_result", key, result, digest([key, "result"])
            )
            print(f"DISCORD_DAILY_DELIVERY_{result['status'].upper()} DATE={record['payload']['date']} SHEET={record['id']} CHANNEL={channel.id} MESSAGE_IDS={result.get('message_ids', [])}", flush=True)

        async def publish_public_preview_once(self):
            from .discord_community import publish_public_preview
            return await publish_public_preview(self, store, config)

        async def publish_loop(self):
            await self.wait_until_ready()
            while not self.is_closed():
                for lane in ("daily", "status", "best_two", "official_picks", "results", "research", "market", "public_preview"):
                    try:
                        await getattr(self, f"publish_{lane}_once")()
                    except Exception as exc:
                        status = getattr(exc, "status", None)
                        response = getattr(exc, "response", None)
                        status = status or getattr(response, "status_code", None)
                        print(f"DISCORD_PUBLISH_{lane.upper()}_{type(exc).__name__}_HTTP_{status}", flush=True)
                        await self.log_operational_failure(lane, exc)
                await asyncio.sleep(60)

        async def close(self):
            task = getattr(self, "publisher", None)
            if task:
                task.cancel()
            await super().close()

    return ResearchClient(
        intents=intents, allowed_mentions=discord.AllowedMentions.none(), max_messages=None,
        chunk_guilds_at_startup=False, member_cache_flags=discord.MemberCacheFlags.none(),
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
        from dataclasses import replace
        from .discord_welcome import enable_member_intent
        config = replace(config, members_enabled=enable_member_intent(token, store))
        build_client(config, store).run(token, log_handler=None)
    finally:
        store.close()


if __name__ == "__main__":
    main()

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from jabazi.discord_access import is_vip_name
from jabazi.discord_bot import BotConfig, build_client, member_has_vip
from jabazi.discord_content import official_pick_embed, performance_text
from jabazi.discord_daily import daily_moneyline, freeze_daily_moneyline, render_text
from jabazi.discord_migration import (
    MANAGE_CHANNELS, MANAGE_ROLES, READ, SEND, VIEW, effective_permissions,
    migrate, overwrites, request,
)
from jabazi.persistence.store import Store


@pytest.fixture
def store(tmp_path):
    db = Store("sqlite:///" + str(tmp_path / "discord.db"), initialize=True)
    yield db
    db.close()


def test_unapproved_vip_substrings_cannot_grant_access():
    config = BotConfig(1, 2, 3, 4, frozenset())
    for name in ("NOT VIP", "EXPIRED VIP", "VIP WAITLIST", "VIPER", "VIP REQUEST"):
        assert not is_vip_name(name)
        assert not member_has_vip(config, NS(id=5, roles=[NS(id=9, name=name)]))
    for name in ("VIP", "JABBAZI VIP", "FOUNDING VIP", "TRIAL VIP", "💎 JABBAZI GURU VIP ACCESS"):
        assert member_has_vip(config, NS(id=5, roles=[NS(id=9, name=name)]))


def test_commands_sync_nonempty_guild_and_private_vip_rechecks_current_roles(store):
    import discord

    async def exercise():
        client = build_client(BotConfig(1, 2, 3, 4, frozenset()), store)
        async def sync(tree, *, guild):
            return tree.get_commands(guild=guild)
        with patch.object(discord.app_commands.CommandTree, "sync", sync):
            await client._async_setup_hook()
            await client.setup_hook()
        guild_id = discord.Object(id=1)
        assert {c.name for c in client.tree.get_commands(guild=guild_id)} == {"vip", "cheatsheet", "alerts", "support"}
        fetched = NS(id=5, roles=[NS(id=8, name="JABBAZI VIP")])
        interaction = NS(guild_id=1, user=NS(id=5, roles=[]),
                         guild=NS(fetch_member=AsyncMock(return_value=fetched)),
                         response=NS(defer=AsyncMock(), send_message=AsyncMock()),
                         followup=NS(send=AsyncMock()))
        await client.tree.get_command("vip", guild=guild_id).callback(interaction)
        interaction.guild.fetch_member.assert_awaited_once_with(5)
        assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
        assert "/vip#access=" in interaction.followup.send.call_args.args[0]
        # Removing the role immediately blocks the next issuance, independent of billing.
        interaction.guild.fetch_member.return_value = NS(id=5, roles=[])
        count = len(store.list_records("member_ticket", 50))
        await client.tree.get_command("vip", guild=guild_id).callback(interaction)
        assert len(store.list_records("member_ticket", 50)) == count
        assert "/vip#access=" not in interaction.followup.send.call_args.args[0]
        await client.tree.get_command("cheatsheet", guild=guild_id).callback(interaction)
        assert "requires an approved VIP role" in interaction.followup.send.call_args.args[0]
        assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
        await client.close()
    asyncio.run(exercise())


def test_prefix_vip_sends_ticket_only_by_dm(store):
    async def exercise():
        client = build_client(BotConfig(1, 2, 3, 4, frozenset()), store)
        client._connection.user = NS(id=9)
        member = NS(id=5, roles=[NS(id=8, name="VIP")], send=AsyncMock())
        channel = NS(id=33, send=AsyncMock())
        message = NS(guild=NS(id=1, fetch_member=AsyncMock(return_value=member)),
                     channel=channel, author=NS(id=5, bot=False), webhook_id=None,
                     content="!vip", mentions=[], id=77)
        await client.on_message(message)
        member.send.assert_awaited_once()
        assert "/vip#access=" in member.send.call_args.kwargs["embed"].url
        assert all("access=" not in str(call) for call in channel.send.call_args_list)
        await client.close()
    asyncio.run(exercise())


def test_full_frozen_slate_survives_long_render_and_repeated_reads(store):
    now = datetime.now(UTC)
    rows = [{"sport": "baseball_mlb", "event_id": str(i), "event": f"Away {i} @ Home {i}",
             "selection": f"Home {i}", "market": "h2h", "status": "WATCH", "executable": True}
            for i in range(90)]
    source = {"id": "source", "payload": {"healthy": True, "completed_at": now.isoformat(), "rows": rows}}
    assert freeze_daily_moneyline(store, source, now=now)[1]
    first = daily_moneyline(store, now=now)
    text = render_text(first)
    assert len(text) > 3900 and "Home 89" in text
    source["payload"]["rows"] = []
    assert not freeze_daily_moneyline(store, source, now=now)[1]
    assert daily_moneyline(store, now=now) == first


def test_stale_source_cannot_be_frozen(store):
    now = datetime.now(UTC)
    source = {"id": "old", "payload": {"healthy": True, "completed_at": (now-timedelta(hours=1)).isoformat(), "rows": []}}
    with pytest.raises(ValueError, match="fresh"):
        freeze_daily_moneyline(store, source, now=now)


def test_main_card_rejects_expired_cash_approval_and_shadow_stage():
    now = datetime.now(UTC)
    payload = {"decision": "BET_NOW", "stake": "30", "maximum_playable_decimal": "1.9",
               "reliability": {"model_can_influence_cash": True, "model_stage": "PRODUCTION_APPROVED"},
               "price": {"best_book": "book", "best_decimal": "2", "executable": True,
                         "observed_at": now.isoformat(), "source_timestamp": now.isoformat(),
                         "starts_at": (now+timedelta(hours=2)).isoformat()}}
    assert official_pick_embed(payload, now=now)
    assert official_pick_embed(payload, now=now+timedelta(minutes=6)) is None
    payload["reliability"]["model_stage"] = "SHADOW_ONLY"
    assert official_pick_embed(payload, now=now) is None


def test_results_exclude_user_sprinkles():
    groups = [{"sport": "MLB", "market": "h2h", "origin": "scanner", "settled": 1, "wins": 0, "losses": 1, "profit_units": -1},
              {"sport": "USER_ONLY", "market": "h2h", "origin": "user", "settled": 1, "profit_units": 100}]
    text = performance_text({"groups": groups})
    assert "USER_ONLY" not in text and "-1.00u" in text


def test_manual_roles_are_not_billing_reconciliation_targets(monkeypatch):
    from jabazi.discord_roles import configured, sync_member_role
    monkeypatch.setenv("JABBAZI_DISCORD_BOT_TOKEN", "test")
    monkeypatch.setenv("JABBAZI_DISCORD_GUILD_ID", "1")
    monkeypatch.setenv("JABBAZI_DISCORD_VIP_ROLE_ID", "7")
    monkeypatch.delenv("JABBAZI_DISCORD_BILLING_ROLE_ID", raising=False)
    assert not configured()
    assert sync_member_role(None, "5")["status"] == "UNCONFIGURED"
    monkeypatch.setenv("JABBAZI_DISCORD_BILLING_ROLE_ID", "7")
    assert not configured()


def test_permission_simulation_checks_free_vip_staff_owner_bot():
    roles = [{"id": "1", "permissions": str(VIEW | SEND | READ)}, {"id": "7", "permissions": "0"},
             {"id": "8", "permissions": "0"}, {"id": "10", "permissions": "0"}]
    for access in ("public", "vip", "staff"):
        channel = {"permission_overwrites": overwrites(access, guild="1", owner="2", bot="9", vip={"7", "8"}, staff={"10"})}
        assert not any(row["id"] == "2" for row in channel["permission_overwrites"])
        for member, assigned, expected in (("free", [], access == "public"), ("vip", ["7"], access != "staff"),
                                           ("vip2", ["8"], access != "staff"), ("mod", ["10"], True), ("2", [], True), ("9", [], True)):
            assert bool(effective_permissions("1", member, assigned, roles, channel, "2") & VIEW) == expected


@pytest.mark.parametrize("archive_blocked", [False, True])
@pytest.mark.parametrize("admin_staff", [False, True])
def test_migration_backs_up_before_changes_reuses_ids_hides_duplicates(tmp_path, monkeypatch, archive_blocked, admin_staff):
    monkeypatch.setenv("JABBAZI_DISCORD_BOT_TOKEN", "NEVER_PRINT_ME")
    monkeypatch.setenv("JABBAZI_DISCORD_GUILD_ID", "1")
    monkeypatch.setenv("JABBAZI_DISCORD_OWNER_ID", "2")
    monkeypatch.setenv("JABBAZI_DISCORD_SUPPORT_CHANNEL_ID", "22")
    monkeypatch.setenv("JABBAZI_DISCORD_STATUS_CHANNEL_ID", "25")
    url = "sqlite:///" + str(tmp_path / "migration.db")
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    backup = Store(url, initialize=True)
    roles = [{"id": "1", "name": "@everyone", "permissions": str(VIEW | SEND | READ), "position": 0},
             {"id": "7", "name": "VIP", "permissions": "0", "position": 1},
             {"id": "8", "name": "VIP", "permissions": "0", "position": 2},
             {"id": "10", "name": "MODERATOR", "permissions": "0", "position": 3},
             {"id": "11", "name": "BOT", "permissions": str(MANAGE_CHANNELS | MANAGE_ROLES), "position": 10}]
    if admin_staff:
        roles.append({"id": "12", "name": "JABBAZI TEAM", "permissions": str(1 << 3), "position": 2})
    channels = [{"id": "20", "name": "╰➤ 🏆 VIP PICKS", "type": 4, "permission_overwrites": []},
                {"id": "21", "name": "🧩│vip-parlays", "type": 0, "parent_id": "20", "permission_overwrites": []},
                {"id": "22", "name": "open-a-ticket", "type": 0, "parent_id": "20", "permission_overwrites": []},
                {"id": "23", "name": "🎾│tennis-chat", "type": 0, "parent_id": "20", "permission_overwrites": [
                    {"id": "7", "type": 0, "allow": str(VIEW), "deny": "0"}]},
                {"id": "24", "name": "🧩│vip-parlays", "type": 0, "parent_id": "20", "permission_overwrites": []}]
    channels.append({"id": "26", "name": "💎│vip-chat", "type": 0, "parent_id": "20", "permission_overwrites": []})
    original = copy.deepcopy(channels)
    channels.append({"id": "27", "name": "╰➤ 🔒 OWNER HISTORY", "type": 4, "permission_overwrites": [{"id": "1", "type": 0, "allow": "0", "deny": str(VIEW)}]})
    channels.append({"id": "25", "name": "🔒│owner-archive", "type": 0, "parent_id": "27", "permission_overwrites": [{"id": "1", "type": 0, "allow": "0", "deny": str(VIEW)}]})
    original = copy.deepcopy(channels)
    mutations = []
    def handler(req):
        path = req.url.path.removeprefix("/api/v10")
        if req.method != "GET":
            assert backup.list_records("discord_server_backup", 1, entity="1"), "write occurred before backup"
            mutations.append(req.method)
        if path == "/guilds/1": value = {"id": "1", "owner_id": "2"}
        elif path == "/users/@me": value = {"id": "9"}
        elif path == "/guilds/1/members/9": value = {"roles": ["11"]}
        elif path == "/oauth2/applications/@me": value = {"id": "9", "name": "JABBAZI GURU"}
        elif path == "/applications/9/guilds/1/commands": value = []
        elif path == "/guilds/1/roles":
            if req.method == "POST":
                value = {"id": str(100+len(roles)), **json.loads(req.content)}
                roles.append(value)
            else: value = roles
        elif path == "/guilds/1/channels":
            if req.method == "POST":
                value = {"id": str(1000+len(channels)), **json.loads(req.content)}
                channels.append(value)
            elif req.method == "PATCH":
                for row in json.loads(req.content):
                    next(c for c in channels if c["id"] == row["id"]).update(row)
                value = channels
            else: value = channels
        elif path.endswith("/messages/pins"): value = {"items": [], "has_more": False}
        elif path.endswith("/messages"): value = []
        elif path.startswith("/channels/"):
            if path == "/channels/23" and archive_blocked:
                return httpx.Response(403, json={"code": 50013, "message": "NEVER_PRINT_ME"})
            value = next(c for c in channels if c["id"] == path.split("/")[2])
            value.update(json.loads(req.content))
        else: raise AssertionError(path)
        return httpx.Response(200, json=copy.deepcopy(value))
    real_client = httpx.Client
    monkeypatch.setattr("jabazi.discord_migration.httpx.Client", lambda **kw: real_client(**kw, transport=httpx.MockTransport(handler), trust_env=False))
    dry = migrate(archive_obsolete=True)
    assert not mutations and dry["mode"] == "DRY_RUN"
    result = migrate(apply=True, archive_obsolete=True)
    assert "parlays-sgps" not in result["channel_ids"]
    assert not effective_permissions("1", "vip", ["7"], roles, next(c for c in channels if c["id"] == "21"), "2") & VIEW
    assert result["channel_ids"]["support"] == "22"
    assert len(result["channel_ids"]) == 18
    assert result["channel_ids"]["vip-lounge"] == "26"
    assert result["channel_ids"]["scanner-status"] != "25"
    assert next(c for c in channels if c["id"] == "25") == original[-1]
    assert next(c for c in channels if c["id"] == "27")["name"].startswith("🗄️ ARCHIVE ·")
    archived = next(c for c in channels if c["id"] == "23")
    assert bool(effective_permissions("1", "vip", ["7"], roles, archived, "2") & VIEW) == archive_blocked
    assert any("ARCHIVE_CHANNEL_HTTP_403_PATH_/channels/23_CODE_50013" in warning for warning in result["warnings"]) == archive_blocked
    assert all(row["status"] == "VERIFIED" for row in result["verification"])
    snapshot = backup.list_records("discord_server_backup", 1, entity="1")[0]["payload"]
    assert snapshot["channels"] == original
    assert "NEVER_PRINT_ME" not in json.dumps(result) + json.dumps(snapshot)
    assert "DELETE" not in mutations
    backup.close()


def test_403_names_the_exact_operation_and_never_response_secrets():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403, text="SECRET")), base_url="https://discord.com", trust_env=False) as http:
        with pytest.raises(RuntimeError, match="DISCORD_OPERATION_MOVE_CHANNEL_HTTP_403") as caught:
            request(http, "PATCH", "/channels/1", "MOVE_CHANNEL", json={})
        assert "SECRET" not in str(caught.value)


def test_support_and_alert_workflows_are_private_and_role_limited(store):
    import discord

    async def exercise():
        client = build_client(BotConfig(1, 2, 3, 4, frozenset(), support_channel=20), store)
        async def sync(tree, *, guild):
            return tree.get_commands(guild=guild)
        with patch.object(discord.app_commands.CommandTree, "sync", sync):
            await client._async_setup_hook()
            await client.setup_hook()
        safe = NS(id=50, name="NFL Alerts", permissions=NS(value=0), managed=False, position=1)
        unsafe = NS(id=51, name="Promo Alerts", permissions=NS(value=8), managed=False, position=1)
        member = NS(id=5, roles=[], add_roles=AsyncMock(), remove_roles=AsyncMock())
        guild = NS(id=1, roles=[safe, unsafe], me=NS(top_role=NS(position=9)), fetch_member=AsyncMock(return_value=member))
        interaction = NS(guild_id=1, guild=guild, user=member,
                         response=NS(send_message=AsyncMock(), defer=AsyncMock()), followup=NS(send=AsyncMock()))
        await client.tree.get_command("alerts", guild=discord.Object(id=1)).callback(interaction)
        assert interaction.response.send_message.call_args.kwargs["ephemeral"]
        select = interaction.response.send_message.call_args.kwargs["view"].children[0]
        select._values = ["Promo Alerts"]
        await select.callback(interaction)
        member.add_roles.assert_not_awaited()
        select._values = ["NFL Alerts"]
        await select.callback(interaction)
        member.add_roles.assert_awaited_once_with(safe, reason="JABBAZI alert preference")
        thread = NS(mention="<private-thread>", add_user=AsyncMock(), send=AsyncMock())
        channel = NS(guild=guild, create_thread=AsyncMock(return_value=thread))
        client.fetch_channel = AsyncMock(return_value=channel)
        await client.tree.get_command("support", guild=discord.Object(id=1)).callback(interaction, "VIP access")
        assert channel.create_thread.call_args.kwargs["type"] == discord.ChannelType.private_thread
        assert channel.create_thread.call_args.kwargs["invitable"] is False
        thread.add_user.assert_awaited_once_with(member)
        assert interaction.followup.send.call_args.kwargs["ephemeral"]
        await client.close()
    asyncio.run(exercise())


def test_closed_dm_vip_fallback_is_private(store):
    import discord

    async def exercise():
        client = build_client(BotConfig(1, 2, 3, 4, frozenset(), support_channel=20), store)
        client._connection.user = NS(id=9)
        forbidden = discord.Forbidden(NS(status=403, reason="Forbidden"), {"message": "DM closed", "code": 50007})
        member = NS(id=5, roles=[NS(id=8, name="VIP")], send=AsyncMock(side_effect=forbidden))
        public = NS(id=33, send=AsyncMock())
        guild = NS(id=1, fetch_member=AsyncMock(return_value=member))
        thread = NS(mention="<private-thread>", add_user=AsyncMock(), send=AsyncMock())
        support = NS(guild=guild, create_thread=AsyncMock(return_value=thread))
        client.fetch_channel = AsyncMock(return_value=support)
        message = NS(guild=guild, channel=public, author=NS(id=5, bot=False), webhook_id=None,
                     content="!vip", mentions=[], id=77)
        await client.on_message(message)
        assert support.create_thread.call_args.kwargs["type"] == discord.ChannelType.private_thread
        assert not support.create_thread.call_args.kwargs["invitable"]
        assert "/vip#access=" in thread.send.call_args.kwargs["embed"].url
        assert all("access=" not in str(call) for call in public.send.call_args_list)
        await client.close()
    asyncio.run(exercise())


def test_unconfigured_billing_does_not_query_or_revoke_manual_members(store, monkeypatch):
    from jabazi.discord_roles import reconcile_known
    monkeypatch.delenv("JABBAZI_DISCORD_BILLING_ROLE_ID", raising=False)
    assert reconcile_known(store)["status"] == "UNCONFIGURED"


@pytest.mark.parametrize("day,hour", [("2026-09-30", 14), ("2026-12-01", 15)])
def test_daily_scheduler_uses_chicago_dst_and_durable_slot(store, day, hour):
    from jabazi.discord_schedule import run_due
    at = datetime.fromisoformat(f"{day}T{hour:02}:00:00+00:00")
    factory = NS()
    with patch("jabazi.automation.AutomaticScanner") as scanner:
        scanner.return_value.run.return_value = NS(errors=["provider unavailable"])
        with patch("jabazi.discord_sheets.archive_sheets", return_value="research-id"):
            assert run_due(factory, store, now=at-timedelta(seconds=1)) == "NOT_DUE"
            assert run_due(factory, store, now=at) == "DATA_UNHEALTHY"
            assert run_due(factory, store, now=at+timedelta(seconds=10)) == "ALREADY_CLAIMED"
            assert run_due(factory, store, now=at+timedelta(minutes=15)) == "NOT_DUE"
            scanner.return_value.run.assert_called_once_with("moneyline")

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from jabazi.discord_bot import BotConfig, brand_trigger, command_allowed, validate_target
from jabazi.discord_sheets import (
    archive_sheets,
    latest_sheet,
    parse_command,
    scanner_status,
    sheet_csv,
)
from jabazi.persistence.store import Store


def test_brand_response_is_owner_only_explicit_and_channel_scoped():
    config = BotConfig(
        1,
        2,
        3,
        4,
        frozenset(),
        frozenset({5}),
        "https://cdn.discordapp.com/attachments/one/logo.gif",
    )
    args = {
        "guild": 1,
        "channel": 5,
        "author": 2,
        "bot_author": False,
        "content": "<@9> new post",
        "mentioned_ids": {9},
        "bot_id": 9,
    }
    assert brand_trigger(config, **args)
    for changes in (
        {"author": 8},
        {"guild": 8},
        {"channel": 8},
        {"bot_author": True},
        {"mentioned_ids": set(), "content": "@everyone"},
        {"mentioned_ids": set(), "content": "!guruspam"},
    ):
        assert not brand_trigger(config, **(args | changes))
    assert brand_trigger(config, **(args | {"mentioned_ids": set(), "content": "!guru"}))


def test_brand_asset_cannot_be_arbitrary_external_url():
    config = BotConfig(1, 2, 3, 4, frozenset(), frozenset({5}), "https://example.com/logo.gif")
    assert not brand_trigger(
        config,
        guild=1,
        channel=5,
        author=2,
        bot_author=False,
        content="!guru",
        mentioned_ids=set(),
        bot_id=9,
    )


@pytest.fixture
def store(tmp_path):
    value = Store("sqlite:///" + str(tmp_path / "tools.db"), initialize=True)
    yield value
    value.close()


def action(sport="baseball_mlb", participant=None):
    now = datetime.now(UTC)
    return SimpleNamespace(
        price=SimpleNamespace(
            sport=sport,
            event='=HYPERLINK("bad")',
            market="h2h",
            selection="Home",
            line=None,
            best_book="Example",
            best_decimal=D("2.1"),
            source_timestamp=now,
            starts_at=now + timedelta(hours=1),
            consensus_probability=D(".5"),
            participant=participant,
        ),
        model_probability=None,
        model_version=None,
        uncertainty=None,
        probability_edge=None,
        expected_roi=None,
        reason="No model available",
    )


def result(actions=(), errors=()):
    return SimpleNamespace(actions=actions, errors=errors, feeds_scanned=3, quotes_archived=30)


def test_sheet_is_immutable_and_does_not_fabricate_model_values(store):
    now = datetime.now(UTC)
    key = archive_sheets(store, result([action()]), now=now)
    record = latest_sheet(store, now=now)
    assert record["id"] == key
    row = record["payload"]["rows"][0]
    assert row["research_probability"] is None
    assert row["expected_roi"] is None
    assert row["status"] == "RESEARCH / NOT AN OFFICIAL PICK"
    assert b"'=HYPERLINK" in sheet_csv(record, "mlb")
    assert len(sheet_csv(record, "nfl").splitlines()) == 1
    with pytest.raises(ValueError):
        sheet_csv(record, "unknown")


def test_latest_failed_scan_does_not_fall_back_to_old_healthy_sheet(store):
    now = datetime.now(UTC)
    archive_sheets(store, result([action()]), now=now - timedelta(minutes=1))
    archive_sheets(store, result(errors=["provider unavailable"]), now=now)
    assert latest_sheet(store, now=now)["payload"]["healthy"] is False


def test_stale_and_future_sheets_are_unavailable(store):
    now = datetime.now(UTC)
    archive_sheets(store, result(), now=now)
    assert latest_sheet(store, now=now + timedelta(hours=4)) is None
    assert latest_sheet(store, now=now - timedelta(seconds=1)) is None


def test_cfb_player_markets_are_excluded(store):
    archive_sheets(store, result([action("americanfootball_ncaaf", "Player Name")]))
    assert latest_sheet(store)["payload"]["rows"] == []


def test_status_reports_missing_stale_and_unhealthy_worker(store):
    now = datetime.now(UTC)
    assert "UNAVAILABLE" in scanner_status(store, now=now)
    store.append(
        "worker_heartbeat",
        "research_worker",
        {"status": "DATA_UNHEALTHY", "completed_at": now.isoformat()},
    )
    assert "DATA_UNHEALTHY" in scanner_status(store, now=now)
    assert "STALE" in scanner_status(store, now=now + timedelta(minutes=4))


@pytest.mark.parametrize(
    "content,expected",
    [
        ("!vip", ("status", ())),
        ("!cheatsheets NFL", ("sheets", ("nfl",))),
        ("!vip grant me admin", None),
        ("!cheatsheets tennis", None),
        ("hello !vip", None),
    ],
)
def test_only_exact_supported_commands(content, expected):
    assert parse_command(content) == expected


def test_commands_ignore_other_servers_channels_and_bots():
    config = BotConfig(1, 2, 3, 4, frozenset({5}))
    assert command_allowed(config, guild=1, channel=3, bot_author=False, content="!vip")
    for guild, channel, bot in [(9, 3, False), (None, 3, False), (1, 4, False), (1, 3, True)]:
        assert (
            command_allowed(config, guild=guild, channel=channel, bot_author=bot, content="!vip")
            is None
        )


def test_delivery_rejects_public_wrong_guild_and_unapproved_role():
    config = BotConfig(1, 2, 3, 4, frozenset({5}))
    doc = {
        "id": "4",
        "guild_id": "1",
        "type": 0,
        "permission_overwrites": [
            {"id": "1", "type": 0, "deny": "1024", "allow": "0"},
            {"id": "5", "type": 0, "deny": "0", "allow": "1024"},
        ],
    }
    validate_target(doc, config, 6)
    with pytest.raises(ValueError):
        validate_target({**doc, "guild_id": "9"}, config, 6)
    with pytest.raises(ValueError):
        validate_target({**doc, "permission_overwrites": []}, config, 6)
    with pytest.raises(ValueError):
        validate_target(
            {
                **doc,
                "permission_overwrites": doc["permission_overwrites"]
                + [{"id": "99", "type": 0, "deny": "0", "allow": "1024"}],
            },
            config,
            6,
        )


@pytest.mark.parametrize("fail_send", [False, True])
def test_real_sdk_publisher_claims_once_and_audits_uncertain_delivery(store, fail_send):
    import asyncio

    pytest.importorskip("discord")
    from jabazi.discord_bot import build_client

    archive_sheets(store, result([action()]))
    sent = []

    async def exercise():
        client = build_client(BotConfig(1, 2, 3, 4, frozenset()), store)

        async def send(content, **kwargs):
            sent.append((content, kwargs))
            if fail_send:
                raise OSError("simulated ambiguous transport outcome")
            return SimpleNamespace(id=10)

        async def checked(channel_id):
            assert channel_id == 4
            return SimpleNamespace(id=4, send=send)

        client.checked_channel = checked
        await client.publish_once()
        await client.publish_once()
        await client.close()

    asyncio.run(exercise())
    assert len(sent) == 1
    assert "NOT OFFICIAL PICKS" in sent[0][0]
    assert len(sent[0][1]["files"]) == 3
    outcome = store.list_records("sheet_delivery_result", 1)[0]["payload"]
    assert outcome["status"] == ("needs_review" if fail_send else "delivered")

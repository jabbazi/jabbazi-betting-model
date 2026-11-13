"""Fail-closed daily-cheat-sheet outage diagnostics, not betting approvals."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from jabazi.discord_bot import BotConfig, build_client
from jabazi.discord_schedule import daily_failure_notice, run_due
from jabazi.persistence.store import Store


def test_missing_sheet_notice_waits_for_three_scans_and_is_not_a_pick():
    store = Store("sqlite:///:memory:", initialize=True)
    try:
        at_9_10 = datetime(2026, 11, 13, 15, 10, tzinfo=UTC)
        at_9_16 = datetime(2026, 11, 13, 15, 16, tzinfo=UTC)
        assert daily_failure_notice(store, now=at_9_16) is None
        store.append(
            "discord_daily_scan_audit", "2026-11-13",
            {"status": "DATA_UNHEALTHY", "error_count": 1},
        )
        assert daily_failure_notice(store, now=at_9_10) is None
        notice = daily_failure_notice(store, now=at_9_16)
        assert "DELAYED" in notice
        assert "No unverified or stale selections" in notice
        assert "BET NOW" not in notice
        assert "PLAY" not in notice
    finally:
        store.close()


def test_daily_scan_failure_audit_does_not_expose_provider_errors():
    store = Store("sqlite:///:memory:", initialize=True)
    try:
        class FakeScanner:
            def __init__(self, settings, *, max_credits_per_run):
                pass

            def run(self, mode):
                assert mode == "moneyline"
                return NS(errors=["secret provider detail DO_NOT_LOG"], feeds_scanned=2, quotes_archived=0)

        now = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
        with patch("jabazi.discord_sheets.archive_sheets", return_value="archived"):
            assert run_due(NS(api_key="configured"), store, now=now, scanner_factory=FakeScanner) == "DATA_UNHEALTHY"
        audits = store.list_records("discord_daily_scan_audit", 5, entity="2026-11-13")
        assert len(audits) == 1
        assert audits[0]["payload"]["error_count"] == 1
        assert audits[0]["payload"]["feeds_scanned"] == 2
        assert "DO_NOT_LOG" not in str(audits)
        assert run_due(NS(api_key="configured"), store, now=now, scanner_factory=FakeScanner) == "ALREADY_CLAIMED"
    finally:
        store.close()


def test_missing_sheet_outage_notice_is_one_per_channel_and_day():
    store = Store("sqlite:///:memory:", initialize=True)
    try:
        client = build_client(BotConfig(1, 2, 3, 4, frozenset()), store)
        channel = NS(id=4, send=AsyncMock(return_value=NS(id=123)))
        client.checked_channel = AsyncMock(return_value=channel)
        with patch("jabazi.discord_schedule.daily_failure_notice", return_value="⚠️ delayed: research only"):
            asyncio.run(client.publish_daily_outage_notice_once())
            asyncio.run(client.publish_daily_outage_notice_once())
        assert channel.send.await_count == 1
        records = store.list_records("discord_daily_outage_result", 5, entity="4")
        assert len(records) == 1
        assert records[0]["payload"]["status"] == "delivered"
    finally:
        store.close()


def _daily_result(*, errors=("baseball_mlb:score_model_load_ValueError",), events=None, stake="0", decision="WATCH", quotes=3):
    from jabazi.automation import AutomaticScanResult
    game = {
        "sport": "basketball_nba", "event_id": "nba-1", "event": "Away @ Home",
        "starts_at_utc": "2026-11-13T22:00:00+00:00", "event_status": "scheduled",
    }
    return AutomaticScanResult(
        feeds_scanned=2, quotes_archived=quotes, new_actions=(), arbitrages=(),
        credits_remaining=10, errors=errors,
        actions=((NS(stake=stake, decision=NS(value=decision)),)
                 if stake != "0" or decision != "WATCH" else ()),
        slate_events=tuple(events if events is not None else [game]),
    )


def test_off_slate_mlb_failure_can_only_recover_research_without_wagers():
    from jabazi.discord_schedule import scoped_non_mlb_daily_result
    now = datetime(2026, 11, 13, 15, tzinfo=UTC)
    original = _daily_result()
    recovered = scoped_non_mlb_daily_result(original, now=now)
    assert recovered is not None and recovered.errors == ()
    assert original.errors == ("baseball_mlb:score_model_load_ValueError",)
    assert recovered.actions is original.actions
    assert scoped_non_mlb_daily_result(_daily_result(stake="50"), now=now) is None
    assert scoped_non_mlb_daily_result(_daily_result(decision="BET_NOW"), now=now) is None
    assert scoped_non_mlb_daily_result(_daily_result(quotes=0), now=now) is None
    assert scoped_non_mlb_daily_result(_daily_result(errors=("basketball_nba:ValueError",)), now=now) is None
    assert scoped_non_mlb_daily_result(_daily_result(errors=(
        "baseball_mlb:score_model_load_ValueError", "icehockey_nhl:missing"
    )), now=now) is None
    mlb_game = {
        "sport": "baseball_mlb", "event_id": "mlb-1", "event": "Away @ Home",
        "starts_at_utc": "2026-11-13T22:00:00+00:00", "event_status": "scheduled",
    }
    assert scoped_non_mlb_daily_result(_daily_result(events=[mlb_game]), now=now) is None
    assert scoped_non_mlb_daily_result(_daily_result(events=[]), now=now) is None


def test_recovery_disabled_by_default_even_for_off_slate_mlb(monkeypatch):
    store = Store("sqlite:///:memory:", initialize=True)
    try:
        class FakeScanner:
            def __init__(self, settings, *, max_credits_per_run):
                pass
            def run(self, mode):
                assert mode == "moneyline"
                return _daily_result()

        at = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
        monkeypatch.delenv("JABBAZI_DAILY_OFF_SLATE_MODEL_RECOVERY", raising=False)
        with patch("jabazi.discord_sheets.archive_sheets", return_value="archived"):
            assert run_due(NS(api_key="yes"), store, now=at, scanner_factory=FakeScanner) == "DATA_UNHEALTHY"
    finally:
        store.close()


def test_scoped_recovery_marks_snapshot_and_daily_text(monkeypatch):
    from jabazi.discord_sheets import archive_sheets
    from jabazi.discord_daily import freeze_daily_moneyline, daily_moneyline
    from jabazi.discord_schedule import (
        scoped_non_mlb_daily_result, scoped_daily_disclosure, daily_delivery_eligible,
    )

    store = Store("sqlite:///:memory:", initialize=True)
    try:
        at = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
        original = _daily_result()
        recovered = scoped_non_mlb_daily_result(original, now=at)
        assert recovered is not None
        archived_original = archive_sheets(store, original, now=at)
        sheet_id = archive_sheets(
            store, recovered, now=at,
            source_model_exclusions=original.errors, entity="daily_scoped_scan",
        )
        original_rows = store.list_records("research_sheet", 5, entity="latest_scan")
        assert len(original_rows) == 1
        assert original_rows[0]["id"] == archived_original
        assert original_rows[0]["payload"]["healthy"] is False
        sheet = next(row for row in store.list_records("research_sheet", 5, entity="daily_scoped_scan")
                     if row["id"] == sheet_id)
        assert sheet["payload"]["daily_scoped_research_only"] is True
        assert sheet["payload"]["source_model_exclusions"] == list(original.errors)
        assert sheet["payload"]["healthy"] is True
        freeze_daily_moneyline(store, sheet, now=at)
        frozen = daily_moneyline(store, now=at)
        assert "daily_scoped_research_only" not in frozen["payload"]
        assert frozen["payload"]["row_count"] == 1
        assert frozen["payload"]["rows"][0]["status"] == "PASS"
        assert "off-slate MLB" in scoped_daily_disclosure(store, frozen)
        assert daily_delivery_eligible(store, frozen, frozen["payload"]["rows"], now=at)
        assert original.errors  # Original scan remains fail-closed.
    finally:
        store.close()



def test_discord_delivery_channel_mapping_flags_missing_and_stale_ids():
    from tools.verify_jabbazi_discord import delivery_channel_findings

    known = {"scanner-status": "100", "cheat-sheets": "200"}
    visible = {"100", "200", "300"}
    env = {"JABBAZI_DISCORD_STATUS_CHANNEL_ID": "300", "JABBAZI_DISCORD_SHEETS_CHANNEL_ID": "200"}
    assert delivery_channel_findings(known, visible, env) == [
        "CHANNEL_CONFIG_DIFFERS_FROM_BLUEPRINT:status"
    ]
    env["JABBAZI_DISCORD_STATUS_CHANNEL_ID"] = "400"
    assert delivery_channel_findings(known, visible, env) == [
        "CHANNEL_UNAVAILABLE_OR_STALE:status"
    ]
    env["JABBAZI_DISCORD_STATUS_CHANNEL_ID"] = "100"
    env["JABBAZI_DISCORD_SHEETS_CHANNEL_ID"] = ""
    assert delivery_channel_findings(known, visible, env) == [
        "CHANNEL_CONFIG_MISSING:sheets"
    ]
    env["JABBAZI_DISCORD_SHEETS_CHANNEL_ID"] = "200"
    assert delivery_channel_findings(known, visible, env) == []



def test_private_discord_delivery_preflight_enforces_scope_and_permissions(monkeypatch):
    from jabazi.discord_migration import VIEW, SEND
    from tools.verify_discord_delivery import validate_private_test_target, main

    roles = [{"id": "1", "permissions": "0"}]
    channel = {
        "id": "3", "guild_id": "1", "type": 0,
        "permission_overwrites": [
            {"id": "1", "type": 0, "allow": "0", "deny": str(VIEW)},
            {"id": "2", "type": 1, "allow": str(VIEW | SEND), "deny": "0"},
        ],
    }
    def check(row):
        return validate_private_test_target("1", "9", "2", [], roles, row)
    assert check(channel) == "VERIFIED_PRIVATE_TARGET"
    assert check({**channel, "guild_id": "20"}) == "WRONG_GUILD_OR_CHANNEL_TYPE"
    assert check({**channel, "type": 4}) == "WRONG_GUILD_OR_CHANNEL_TYPE"
    missing_bot = {**channel, "permission_overwrites": channel["permission_overwrites"][:1]}
    assert check(missing_bot) == "BOT_VIEW_SEND_NOT_GRANTED"
    public = {
        **channel,
        "permission_overwrites": [
            {"id": "1", "type": 0, "allow": str(VIEW), "deny": "0"},
            channel["permission_overwrites"][1],
        ],
    }
    assert check(public) == "NOT_EXPLICITLY_PRIVATE"
    monkeypatch.delenv("JABBAZI_DISCORD_BOT_TOKEN", raising=False)
    assert main([]) == 2


def test_scoped_delivery_rejects_stale_or_mutated_sources():
    from jabazi.discord_schedule import daily_delivery_eligible
    from jabazi.discord_sheets import archive_sheets
    from jabazi.discord_daily import freeze_daily_moneyline, daily_moneyline
    from jabazi.discord_schedule import scoped_non_mlb_daily_result
    from datetime import timedelta

    store = Store("sqlite:///:memory:", initialize=True)
    try:
        at = datetime(2026, 11, 13, 15, tzinfo=UTC)
        original = _daily_result()
        recovered = scoped_non_mlb_daily_result(original, now=at)
        sid = archive_sheets(store, recovered, now=at,
            source_model_exclusions=original.errors, entity="daily_scoped_scan")
        sheet = next(x for x in store.list_records("research_sheet", 5, entity="daily_scoped_scan") if x["id"] == sid)
        freeze_daily_moneyline(store, sheet, now=at)
        record = daily_moneyline(store, now=at)
        rows = record["payload"]["rows"]
        assert daily_delivery_eligible(store, record, rows, now=at)
        assert not daily_delivery_eligible(store, record, rows, now=at+timedelta(minutes=16))
        bad = [{**rows[0], "event_id":"foreign-game"}]
        assert not daily_delivery_eligible(store, record, bad, now=at)
        assert not daily_delivery_eligible(store, record, [], now=at)
        assert not daily_delivery_eligible(store, {**record, "payload": {
            **record["payload"], "source_research_sheet_id":"unknown"
        }}, rows, now=at)
    finally:
        store.close()


def test_scoped_archive_rejects_any_promotion_to_global_health():
    import pytest
    from jabazi.discord_sheets import archive_sheets
    store = Store("sqlite:///:memory:", initialize=True)
    try:
        result = _daily_result(errors=())
        with pytest.raises(ValueError):
            archive_sheets(store, result, source_model_exclusions=("MLB",))
        with pytest.raises(ValueError):
            archive_sheets(store, result, entity="daily_scoped_scan")
        assert store.list_records("research_sheet", 10) == []
    finally:
        store.close()


def test_opt_in_daily_flow_freezes_only_isolated_research(monkeypatch):
    """Real freeze and readback, no writing healthy status over global failed scan."""
    from jabazi import discord_schedule, discord_sheets
    from jabazi.discord_daily import daily_moneyline

    at = datetime(2026, 11, 13, 15, tzinfo=UTC)
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz is not None else at.replace(tzinfo=None)

    class FakeScanner:
        def __init__(self, settings, *, max_credits_per_run):
            assert max_credits_per_run > 0
        def run(self, mode):
            assert mode == "moneyline"
            return _daily_result()

    store = Store("sqlite:///:memory:", initialize=True)
    try:
        monkeypatch.setenv("JABBAZI_DAILY_OFF_SLATE_MODEL_RECOVERY", "true")
        monkeypatch.setattr(discord_schedule, "datetime", FixedDateTime)
        monkeypatch.setattr(discord_sheets, "datetime", FixedDateTime)
        assert run_due(NS(api_key="yes"), store, now=at, scanner_factory=FakeScanner) == "FROZEN"
        global_scans = store.list_records("research_sheet", 5, entity="latest_scan")
        scoped_scans = store.list_records("research_sheet", 5, entity="daily_scoped_scan")
        assert len(global_scans) == len(scoped_scans) == 1
        assert global_scans[0]["payload"]["healthy"] is False
        assert scoped_scans[0]["payload"]["healthy"] is True
        audit = store.list_records("discord_daily_scan_audit", 1, entity="2026-11-13")
        assert audit[0]["payload"]["status"] == "SCOPED_RESEARCH_ONLY"
        assert audit[0]["payload"]["error_count"] == 1
        frozen = daily_moneyline(store, now=at)
        assert frozen["payload"]["source_research_sheet_id"] == scoped_scans[0]["id"]
        assert discord_schedule.daily_delivery_eligible(
            store, frozen, frozen["payload"]["rows"], now=at
        )
        assert "off-slate MLB" in discord_schedule.scoped_daily_disclosure(store, frozen)
        assert run_due(NS(api_key="yes"), store, now=at, scanner_factory=FakeScanner) == "ALREADY_FROZEN"
    finally:
        store.close()

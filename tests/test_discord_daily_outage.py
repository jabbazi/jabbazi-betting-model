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

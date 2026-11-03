from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import json
import uuid
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jabazi.api import app
from jabazi.domain.models import Quote, DataQuality
from jabazi.operations import ClosingCollector, clv_for_entry, finalize_closing
from jabazi.persistence.store import Store
from jabazi.providers.base import ProviderBatch
from jabazi.providers.the_odds_api import TheOddsApiProvider
from jabazi.runtime import doctor, worker


@pytest.fixture(
    params=["sqlite"] + (["postgres"] if os.getenv("JABBAZI_TEST_POSTGRES_URL") else [])
)
def store(request, tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "operations.db")
    admin = None
    schema = None
    if request.param == "postgres":
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url

        admin = create_engine(os.environ["JABBAZI_TEST_POSTGRES_URL"])
        schema = "ops_" + uuid.uuid4().hex
        with admin.begin() as conn:
            conn.execute(text("CREATE SCHEMA " + schema))
        url = (
            make_url(os.environ["JABBAZI_TEST_POSTGRES_URL"])
            .update_query_dict({"options": "-csearch_path=" + schema})
            .render_as_string(hide_password=False)
        )
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    monkeypatch.setenv("JABAZI_ENV", "test")
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "a" * 40)
    monkeypatch.setenv("JABAZI_UNIT_SIZE", "30")
    monkeypatch.setenv("JABAZI_ODDS_API_KEY", "")
    result = Store(url, initialize=True)
    yield result
    result.close()
    if admin is not None:
        with admin.begin() as conn:
            conn.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        admin.dispose()


def quotes(start, *, now=None):
    at = now or start - timedelta(seconds=60)
    return tuple(
        Quote(
            str(uuid.uuid4()),
            "evt",
            "h2h",
            selection,
            book,
            D("1.91"),
            None,
            at,
            at,
            DataQuality.DELAYED,
            "americanfootball_nfl",
            "Away @ Home",
            start,
        )
        for book in ("draftkings", "fanduel")
        for selection in ("Home", "Away")
    )


def test_monthly_budget_is_atomic_and_survives_restart(store):
    def charge(_):
        return store.claim_credits("test", 3, monthly_limit=9, key=uuid.uuid4().hex)

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(charge, range(6))) == 3
    other = Store(store.engine.url.render_as_string(hide_password=False))
    try:
        assert not other.claim_credits("test", 1, monthly_limit=9, key=uuid.uuid4().hex)
    finally:
        other.close()


def test_closing_consensus_requires_same_contract_and_fresh_pregame_quotes(store):
    start = datetime.now(UTC) - timedelta(seconds=1)
    batch = ProviderBatch("fixture", start, b"{}", quotes(start))
    store.archive_batch(batch)
    assert finalize_closing(store, "evt", start) == 2
    assert finalize_closing(store, "evt", start) == 0
    result = clv_for_entry(
        store,
        event_id="evt",
        market="h2h",
        selection="Home",
        line=None,
        participant=None,
        entry_decimal=D("2.1"),
    )
    assert result["probability_clv"] == D(".5") - 1 / D("2.1")
    assert result["price_clv"] == D(".05")
    assert (
        clv_for_entry(
            store,
            event_id="evt",
            market="spreads",
            selection="Home",
            line=D("-3"),
            participant=None,
            entry_decimal=D("2.1"),
        )["status"]
        == "UNAVAILABLE"
    )


def test_post_start_or_stale_quotes_do_not_become_closing_price(store):
    start = datetime.now(UTC) - timedelta(seconds=10)
    for age in (300, -5):
        store.archive_batch(
            ProviderBatch(
                "fixture", start, b"{}", quotes(start, now=start - timedelta(seconds=age))
            )
        )
    assert finalize_closing(store, "evt", start) == 0


def test_collector_reserves_each_slot_once_and_finalizes(store):
    start = datetime.now(UTC) + timedelta(seconds=60)

    class Provider:
        calls = 0

        def __init__(self, sport, **kwargs):
            self.sport = sport

        def list_events(self):
            return (
                [{"id": "evt", "commence_time": start.isoformat()}]
                if self.sport == "americanfootball_nfl"
                else []
            )

        def fetch_event(self, event, markets):
            Provider.calls += 1
            return ProviderBatch("fixture", start, b"{}", quotes(start))

    collector = ClosingCollector(store, "test-only", provider_factory=Provider)
    assert collector.run(start - timedelta(seconds=60))["snapshots"] == 1
    assert collector.run(start - timedelta(seconds=50))["snapshots"] == 0
    assert collector.run(start + timedelta(seconds=1))["closing_proxies"] == 2
    assert Provider.calls == 1


def test_historical_snapshot_keeps_real_timestamp_and_rejects_future_data():
    at = datetime(2025, 1, 1, 12, 3, tzinfo=UTC)
    payload = {"timestamp": "2025-01-01T12:00:00Z", "data": []}
    urls = []

    def transport(url):
        urls.append(url)
        return json.dumps(payload).encode(), {"x-requests-last": "30"}

    p = TheOddsApiProvider("americanfootball_nfl", api_key="test-secret", transport=transport)
    result = p.fetch_historical(at)
    assert result["snapshot_at"] == "2025-01-01T12:00:00+00:00"
    assert "test-secret" not in json.dumps(result)
    assert "/v4/historical/sports/" in urls[0]
    payload["timestamp"] = "2025-01-01T12:05:00Z"
    with pytest.raises(ValueError, match="future"):
        p.fetch_historical(at)


def placement():
    return {
        "idempotency_key": "test-ticket-one",
        "sport": "americanfootball_nfl",
        "event_id": "evt",
        "market": "h2h",
        "selection": "Home",
        "sportsbook": "draftkings",
        "decimal_odds": "2.1",
        "stake": "15.00",
        "placed_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "ticket_reference": "owner-reported-test-ticket",
        "theses": ["evt:home"],
    }


def test_owner_ledger_requires_auth_retains_corrections_and_actual_exposure(store):
    client = TestClient(app)
    body = placement()
    assert client.post("/v1/ledger/import", json=body).status_code == 401
    headers = {"Authorization": "Bearer " + "a" * 40}
    assert client.post("/v1/ledger/import", json=body, headers=headers).status_code == 200
    assert store.open_exposure() == D(15)
    assert not client.post("/v1/ledger/import", json=body, headers=headers).json()["created"]
    changed = {**body, "stake": "30.00"}
    assert client.post("/v1/ledger/import", json=changed, headers=headers).status_code == 409
    settlement = {
        "idempotency_key": "test-settle-one",
        "result": "loss",
        "evidence_reference": "test-result",
    }
    assert (
        client.post("/v1/ledger/test-ticket-one/settle", json=settlement, headers=headers).json()[
            "profit"
        ]
        == "-15.00"
    )
    correction = {**settlement, "idempotency_key": "test-settle-two", "result": "void"}
    assert (
        client.post(
            "/v1/ledger/test-ticket-one/settle", json=correction, headers=headers
        ).status_code
        == 422
    )
    correction["correction_reason"] = "Official void"
    assert (
        client.post(
            "/v1/ledger/test-ticket-one/settle", json=correction, headers=headers
        ).status_code
        == 200
    )
    assert store.open_exposure() == 0
    history = client.get("/v1/ledger/test-ticket-one/history", headers=headers).json()["events"]
    assert len(history) == 3
    assert history[1]["payload"]["evidence"]["profit"] == "-15.00"
    assert (
        client.get("/v1/ledger/test-ticket-one/clv", headers=headers).json()["status"]
        == "UNAVAILABLE"
    )
    performance = client.get("/v1/performance", headers=headers).json()
    assert performance["total_positions"] == 1
    assert D(performance["groups"][0]["profit"]) == 0
    assert performance["groups"][0]["origin"] == "user"


def test_research_worker_without_provider_waits_without_network_or_bets(store):
    with patch("urllib.request.urlopen", side_effect=AssertionError("network must not run")):
        assert worker(once=True)["status"] == "WAITING_FOR_ODDS_CREDENTIAL"
    assert doctor()["status"] == "READY_FOR_RESEARCH"
    assert not doctor()["betting_enabled"]
    assert (
        store.list_records("worker_heartbeat")[0]["payload"]["status"]
        == "WAITING_FOR_ODDS_CREDENTIAL"
    )


def test_discord_delivery_claim_survives_restart_and_ambiguous_response(store):
    from jabazi.domain.shopping import build_price_cards
    from jabazi.domain.recommendation import ActionCard
    from jabazi.domain.models import Decision
    from jabazi.discord_review import deliver_durable

    card = build_price_cards(quotes(datetime.now(UTC) + timedelta(seconds=60)))[0]
    action = ActionCard(card, Decision.WATCH, D(".55"), None, D(0), None, "Unvalidated")
    with patch("jabazi.discord_review.webhook_request", side_effect=TimeoutError) as send:
        with pytest.raises(RuntimeError):
            deliver_durable(action, "https://discord.com/api/webhooks/1/test", store, "123")
        other = Store(store.engine.url.render_as_string(hide_password=False))
        try:
            assert (
                deliver_durable(action, "https://discord.com/api/webhooks/1/test", other, "123")
                == "already_delivered_or_requires_review"
            )
        finally:
            other.close()
        send.assert_called_once()
    assert store.list_records("delivery_result")[0]["payload"]["status"] == "needs_review"


def test_private_channel_rejects_extra_role_grants(monkeypatch):
    from jabazi.discord_review import verify_private_channel

    for key, value in [
        ("BOT_TOKEN", "test-only"),
        ("GUILD_ID", "111"),
        ("OWNER_ID", "222"),
        ("ANALYST_ROLE_ID", "333"),
    ]:
        monkeypatch.setenv("JABBAZI_DISCORD_" + key, value)
    permissions = [
        {"id": "111", "type": 0, "deny": str(1 << 10), "allow": "0"},
        {"id": "333", "type": 0, "deny": "0", "allow": str(1 << 10)},
    ]

    def request(path):
        if path.startswith("/guilds/"):
            return {"owner_id": "222"}
        if path == "/users/@me":
            return {"id": "444"}
        return {"guild_id": "111", "type": 0, "permission_overwrites": permissions}

    assert verify_private_channel("555", request)["private_overwrites_verified"]
    permissions.append({"id": "999", "type": 0, "deny": "0", "allow": str(1 << 10)})
    with pytest.raises(ValueError, match="Unexpected role"):
        verify_private_channel("555", request)

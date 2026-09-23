import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.member_access import (
    issue_ticket,
    exchange_ticket,
    validate_session,
    portal_origin,
    hashed,
)
from jabazi.member_api import COOKIE
from jabazi.persistence.store import Store


@pytest.fixture
def portal(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "member.db")
    store = Store(url, initialize=True)
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "synthetic-owner-" + "x" * 40)
    monkeypatch.setattr("jabazi.member_api.store_for_request", lambda: Store(url))
    with TestClient(app, base_url=portal_origin()) as client:
        yield store, client
    store.close()


def sign_in(store, client):
    ticket = issue_ticket(store, guild=1, member=2, authorized=True)
    response = client.post(
        "/v1/member/session", json={"ticket": ticket}, headers={"Origin": portal_origin()}
    )
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" in response.headers["set-cookie"].lower()
    return ticket


def test_tickets_are_single_use_hashed_scoped_and_expire(portal):
    store, client = portal
    assert client.get("/vip").status_code == 200
    assert client.get("/v1/member/sheets").status_code == 401
    with pytest.raises(PermissionError):
        issue_ticket(store, guild=1, member=9, authorized=False)
    ticket = sign_in(store, client)
    assert client.get("/v1/member/sheets").status_code == 200
    assert (
        client.post(
            "/v1/member/session", json={"ticket": ticket}, headers={"Origin": portal_origin()}
        ).status_code
        == 401
    )
    assert client.get("/v1/owner/review").status_code == 401
    assert client.post("/v1/scans/run", json={}).status_code == 401
    assert all(ticket not in str(r) for r in store.list_records())
    token = client.cookies.get(COOKIE)
    assert (
        client.get("/v1/owner/review", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )
    with pytest.raises(PermissionError):
        validate_session(store, token, now=datetime.now(UTC) + timedelta(minutes=16))
    assert client.post("/v1/member/logout", headers={"Origin": portal_origin()}).status_code == 200
    assert client.get("/v1/member/sheets").status_code == 401
    with pytest.raises(PermissionError):
        validate_session(store, token)
    expired = issue_ticket(
        store, guild=1, member=2, authorized=True, now=datetime.now(UTC) - timedelta(minutes=6)
    )
    with pytest.raises(PermissionError):
        exchange_ticket(store, expired)


def test_member_view_surfaces_only_supported_edges_and_never_exposes_owner_data(portal):
    store, client = portal
    now = datetime.now(UTC)
    events = [
        {
            "sport": "baseball_mlb",
            "event_id": str(i),
            "event": f"Away {i} @ Home {i}",
            "starts_at_utc": (now + timedelta(hours=2)).isoformat(),
        }
        for i in range(32)
    ]
    store.append(
        "research_sheet",
        "latest_scan",
        {
            "completed_at": now.isoformat(),
            "healthy": True,
            "rows": [],
            "slate_events": events,
            "model_features": "MUST_NOT_EXPOSE",
            "bankroll": 3000,
            "truncated": False,
        },
    )
    sign_in(store, client)
    response = client.get("/v1/member/sheets?sport=mlb")
    payload = response.json()
    assert payload["rows"] == [] and payload["games"] == 0
    assert payload["featured_only"] is True
    assert payload["image_pages"][0] == 1
    assert "MUST_NOT_EXPOSE" not in response.text and "bankroll" not in response.text
    assert client.get("/v1/member/image/mlb/0/2.png").headers["content-type"] == "image/png"
    assert client.get("/v1/member/image/mlb/0/3.png").status_code == 404
    lessons = client.get("/v1/member/learn")
    assert lessons.status_code == 200 and len(lessons.json()) == 20
    assert client.get("/v1/member/sheets?sport=cfb&tab=props").json()["rows"] == []


def test_cross_origin_cannot_consume_a_ticket(portal):
    store, client = portal
    ticket = issue_ticket(store, guild=1, member=2, authorized=True)
    assert (
        client.post(
            "/v1/member/session",
            json={"ticket": ticket},
            headers={"Origin": "https://example.invalid"},
        ).status_code
        == 403
    )
    assert store.list_records("member_ticket_used", 1, entity=hashed(ticket)) == []


def test_vip_command_uses_fresh_roles_and_only_sends_private_access_to_the_member(portal):
    from jabazi.discord_bot import build_client, BotConfig

    store, _ = portal

    async def exercise():
        client = build_client(BotConfig(1, 2, 3, 4, frozenset({5})), store)
        client._connection.user = SimpleNamespace(id=99)
        client.checked_channel = AsyncMock()
        member = SimpleNamespace(id=8, roles=[SimpleNamespace(id=5)], send=AsyncMock())
        guild = SimpleNamespace(id=1, fetch_member=AsyncMock(return_value=member))
        channel = SimpleNamespace(id=4, send=AsyncMock())
        message = SimpleNamespace(
            guild=guild,
            channel=channel,
            author=SimpleNamespace(id=8, bot=False),
            webhook_id=None,
            content="!vip",
            mentions=[],
            id=1,
        )
        await client.on_message(message)
        guild.fetch_member.assert_awaited_once_with(8)
        assert member.send.await_count == 1
        assert "#access=" in member.send.call_args.kwargs["embed"].url
        assert all("#access=" not in str(call) for call in channel.send.call_args_list)
        assert len(store.list_records("member_ticket")) == 1
        # A cached approved role on the message cannot override current membership.
        member.roles = []
        message.author.id = 7
        member.id = 7
        await client.on_message(message)
        assert member.send.await_count == 1 and len(store.list_records("member_ticket")) == 1
        await client.close()

    asyncio.run(exercise())

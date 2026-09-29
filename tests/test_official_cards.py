import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jabazi import official as o
from jabazi.api import app
from jabazi.member_access import (
    check_live_membership,
    MembershipUnavailable,
    issue_ticket,
    portal_origin,
)
from jabazi.persistence.store import Store, Conflict


@pytest.fixture
def store(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "cards.db")
    value = Store(url, initialize=True)
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "synthetic-owner-" + "x" * 40)
    monkeypatch.setenv("JABAZI_UNIT_SIZE", "30")
    yield value
    value.close()


def body(now=None, **changes):
    now = now or datetime.now(UTC)
    return o.IssuePick(
        **(
            {
                "idempotency_key": "synthetic-card-key",
                "card": "main",
                "sport": "mlb",
                "event_id": "synthetic-event",
                "event": "TEST Away @ TEST Home",
                "starts_at": now + timedelta(hours=2),
                "market": "h2h",
                "selection": "TEST Home",
                "sportsbook": "TEST Book",
                "decimal_odds": "2.2",
                "minimum_decimal": "2.1",
                "price_observed_at": now,
                "stake_units": ".5",
                "reasoning": "Synthetic reasoning for isolated testing only.",
                "evidence": "Private evidence reference for tests",
                "risks": "Synthetic lineup uncertainty",
                "owner_reviewed": True,
            }
            | changes
        )
    )


def test_issuance_is_immutable_idempotent_and_does_not_approve_model(store):
    now = datetime.now(UTC)
    b = body(now)
    key, created = o.issue(store, b, now)
    assert created and o.issue(store, b, now)[1] is False
    with pytest.raises(Conflict):
        o.issue(store, b.model_copy(update={"reasoning": "Changed original recommendation"}), now)
    first = o.card_view(store, key, now)
    assert first["stake_dollars"] == "15.00" and first["model_approved"] is False
    assert "evidence" not in first and "position_id" not in first
    assert o.card_view(store, key, now + timedelta(minutes=3))["status"] == "PRICE_EXPIRED"
    assert len(o.history(store, key)) == 1
    assert store.list_records("model_approval") == []


@pytest.mark.parametrize(
    "change",
    [
        {"price_observed_at": datetime.now(UTC) - timedelta(minutes=3)},
        {"price_observed_at": datetime.now(UTC) + timedelta(minutes=3)},
        {"starts_at": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
def test_issuance_rejects_unusable_prices(store, change):
    with pytest.raises(ValueError):
        o.issue(store, body(**change))
    assert not o.all_cards(store)


@pytest.mark.parametrize(
    "change",
    [
        {"card": "sprinkle", "stake_units": ".5"},
        {"minimum_decimal": "2.3"},
        {"decimal_odds": "NaN"},
        {"sport": "cfb", "participant": "TEST Player"},
        {"owner_reviewed": False},
    ],
)
def test_publication_contract_constraints(change):
    with pytest.raises(ValidationError):
        body(**change)


def test_results_keep_losses_withdrawals_and_correction_history(store):
    now = datetime.now(UTC)
    key, _ = o.issue(store, body(now), now)
    update = o.PickUpdate(
        idempotency_key="withdraw-key",
        expected_revision=1,
        status="WITHDRAWN",
        reason="Test starting lineup changed",
    )
    assert o.change(store, key, update, now)
    assert o.change(store, key, update, now) is False
    settle = o.PickResult(
        idempotency_key="result-key-one",
        expected_revision=2,
        result="loss",
        evidence="Synthetic official result reference",
    )
    with pytest.raises(ValueError):
        o.change(store, key, settle, now)
    later = now + timedelta(hours=4)
    o.change(store, key, settle, later)
    with pytest.raises(ValueError, match="correction"):
        o.change(
            store,
            key,
            settle.model_copy(
                update={"idempotency_key": "newresultkey", "expected_revision": 3, "result": "win"}
            ),
            later,
        )
    assert o.performance(o.all_cards(store))["main"]["profit_units"] == "-0.5"
    assert o.performance(o.all_cards(store))["main"]["withdrawn"] == 1
    fix = o.PickResult(
        idempotency_key="corrected-result",
        expected_revision=3,
        result="push",
        evidence="Corrected synthetic grading evidence",
        correction_reason="Original grading used the wrong final score",
    )
    o.change(store, key, fix, later)
    assert [r["payload"].get("result") for r in o.history(store, key)] == [
        None,
        None,
        "loss",
        "push",
    ]
    p = o.performance(o.all_cards(store))["main"]
    assert p["pushes"] == 1 and p["stake_units"] == "0.5" and Decimal(p["roi"]) == 0
    with pytest.raises(Conflict):
        o.change(
            store, key, update.model_copy(update={"idempotency_key": "stale-revision-key"}), later
        )


def test_ledger_sync_links_exact_contract_and_is_idempotent(store):
    now = datetime.now(UTC) - timedelta(hours=4)
    pos = {
        "event": "synthetic-event",
        "market": "h2h",
        "selection": "TEST Home",
        "line": None,
        "participant": None,
        "sportsbook": "TEST Book",
        "stake": "60",
        "decimal_odds": "2.5",
    }
    store.import_placement("private-position", pos)
    key, _ = o.issue(store, body(now, position_id="private-position"), now)
    with pytest.raises(ValueError, match="contract"):
        o.issue(
            store,
            body(
                now,
                idempotency_key="mismatched-card",
                position_id="private-position",
                selection="TEST Away",
            ),
            now,
        )
    store.transition(
        "private-position",
        "settled",
        actor="owner",
        evidence={"result": "win", "profit": "90", "evidence_reference": "synthetic"},
        event_key="settle-source",
    )
    assert o.sync_ledger_results(store) == 1 and o.sync_ledger_results(store) == 0
    c = o.card_view(store, key)
    assert (
        c["profit_units"] == "0.60" and c["result_source"] == "OWNER_LEDGER"
    )  # card price, not private stake
    store.transition(
        "private-position",
        "settled",
        actor="owner",
        evidence={
            "result": "loss",
            "profit": "-60",
            "correction_reason": "Wrong final score",
            "evidence_reference": "synthetic corrected",
        },
        event_key="corrected-source",
    )
    assert o.sync_ledger_results(store) == 1
    assert o.card_view(store, key)["profit_units"] == "-0.5"
    assert len(o.history(store, key)) == 3


def test_member_cards_are_read_only_private_and_paginated(store, monkeypatch):
    monkeypatch.setattr("jabazi.member_access.check_live_membership", lambda _: None)
    monkeypatch.setenv("JABBAZI_DISCORD_GUILD_ID", "1")
    owner = {"Authorization": "Bearer synthetic-owner-" + "x" * 40}
    with TestClient(app, base_url=portal_origin()) as client:
        assert client.get("/owner/picks").status_code == 200
        assert client.get("/v1/member/cards").status_code == 401
        assert client.post("/v1/official", json=body().model_dump(mode="json")).status_code == 401
        for i in range(53):
            o.issue(store, body(idempotency_key="synthetic-" + str(i)))
        ticket = issue_ticket(store, guild=1, member=2, authorized=True)
        assert (
            client.post(
                "/v1/member/session", json={"ticket": ticket}, headers={"Origin": portal_origin()}
            ).status_code
            == 200
        )
        first = client.get("/v1/member/cards").json()
        assert len(first["cards"]) == 50 and first["total"] == 53 and first["has_more"]
        second = client.get("/v1/member/cards?page=2").json()
        assert len(second["cards"]) == 3 and not second["has_more"]
        assert len({r["id"] for r in first["cards"] + second["cards"]}) == 53
        assert client.get("/v1/member/cards?page=0").status_code == 422
        assert client.get("/v1/member/cards?day=bad").status_code == 422
        assert "Private evidence" not in client.get("/v1/member/cards").text
        assert client.get("/v1/official").status_code == 401
        assert client.get("/v1/official", headers=owner).status_code == 200
        assert client.post("/v1/scans/run", json={}).status_code == 401
        monkeypatch.setattr(
            "jabazi.member_access.check_live_membership",
            lambda _: (_ for _ in ()).throw(PermissionError()),
        )
        for path in (
            "/v1/member/cards",
            "/v1/member/me",
            "/v1/member/learn",
            "/v1/member/sheets",
            f"/v1/member/cards/{first['cards'][0]['id']}/history",
        ):
            assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "roles,pending,status,allowed",
    [
        (["5"], False, 200, True),
        (["6"], False, 200, False),
        ([], False, 200, False),
        (["5"], True, 200, False),
        (["5"], False, 404, False),
    ],
)
def test_live_discord_access_requires_current_vip_role(
    monkeypatch, roles, pending, status, allowed
):
    for k, v in {
        "GUILD_ID": "1",
        "OWNER_ID": "2",
        "BOT_TOKEN": "synthetic",
        "VIEWER_ROLE_IDS": "5",
    }.items():
        monkeypatch.setenv("JABBAZI_DISCORD_" + k, v)

    def reply(request):
        assert str(request.url) == "https://discord.com/api/v10/guilds/1/members/8"
        return httpx.Response(
            status, json={"user": {"id": "8"}, "roles": roles, "pending": pending}
        )

    transport = httpx.MockTransport(reply)
    if allowed:
        check_live_membership({"guild": "1", "member": "8"}, transport=transport)
    else:
        with pytest.raises(PermissionError):
            check_live_membership({"guild": "1", "member": "8"}, transport=transport)


def test_membership_rate_limit_fails_closed_and_redacts(monkeypatch):
    for k, v in {
        "GUILD_ID": "1",
        "OWNER_ID": "2",
        "BOT_TOKEN": "secret-must-not-print",
        "VIEWER_ROLE_IDS": "5",
    }.items():
        monkeypatch.setenv("JABBAZI_DISCORD_" + k, v)
    with pytest.raises(MembershipUnavailable) as exc:
        check_live_membership(
            {"guild": "1", "member": "8"},
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, text="secret-must-not-print")
            ),
        )
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("failure", [False, True])
def test_official_delivery_is_private_bounded_and_never_repeats_ambiguous_send(
    store, monkeypatch, failure
):
    from jabazi.official_delivery import publish_official_once
    from jabazi.discord_bot import BotConfig, validate_target

    for name, value in [("MAIN_CARD", 10), ("SPRINKLES", 11), ("PICK_UPDATES", 12)]:
        monkeypatch.setenv("JABBAZI_DISCORD_" + name + "_CHANNEL_ID", str(value))
    o.issue(store, body())
    sender = AsyncMock(
        side_effect=OSError("uncertain transport") if failure else None,
        return_value=SimpleNamespace(id=123),
    )
    client = SimpleNamespace(checked_channel=AsyncMock(return_value=SimpleNamespace(send=sender)))
    config = BotConfig(1, 2, 3, 4, frozenset({5}))
    asyncio.run(publish_official_once(client, store, config))
    asyncio.run(publish_official_once(client, store, config))
    assert sender.await_count == 1
    assert sender.call_args.kwargs["allowed_mentions"].to_dict()["parse"] == []
    text = str(sender.call_args.kwargs["embed"].to_dict())
    assert "synthetic" not in text.lower() or "Private evidence" not in text
    assert store.list_records("official_delivery_result")[0]["payload"]["status"] == (
        "needs_review" if failure else "delivered"
    )
    doc = {
        "id": "10",
        "guild_id": "1",
        "type": 0,
        "permission_overwrites": [
            {"id": "1", "type": 0, "deny": "1024", "allow": "0"},
            {"id": "5", "type": 0, "deny": "0", "allow": "1024"},
        ],
    }
    validate_target(doc, config, 99)
    with pytest.raises(ValueError):
        validate_target({**doc, "permission_overwrites": []}, config, 99)
    with pytest.raises(ValueError):
        validate_target({**doc, "id": "3"}, config, 99)  # VIP cannot see scanner


def test_member_logout_revokes_cookie_during_discord_outage(store, monkeypatch):
    from jabazi.member_access import validate_session
    from jabazi.member_api import COOKIE

    monkeypatch.setenv("JABBAZI_DISCORD_GUILD_ID", "1")
    monkeypatch.setattr("jabazi.member_access.check_live_membership", lambda _: None)
    with TestClient(app, base_url=portal_origin()) as client:
        ticket = issue_ticket(store, guild=1, member=2, authorized=True)
        client.post(
            "/v1/member/session", json={"ticket": ticket}, headers={"Origin": portal_origin()}
        )
        cookie = client.cookies.get(COOKIE)
        monkeypatch.setattr(
            "jabazi.member_access.check_live_membership",
            lambda _: (_ for _ in ()).throw(MembershipUnavailable()),
        )
        assert client.get("/v1/member/cards").status_code == 503
        assert (
            client.post("/v1/member/logout", headers={"Origin": portal_origin()}).status_code == 200
        )
        monkeypatch.setattr("jabazi.member_access.check_live_membership", lambda _: None)
        with pytest.raises(PermissionError):
            validate_session(store, cookie)

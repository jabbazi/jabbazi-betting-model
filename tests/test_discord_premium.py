import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from jabazi.discord_daily import freeze_daily_moneyline, daily_moneyline, render_text
from jabazi.discord_entitlements import set_entitlement, latest_entitlement, active_members
from jabazi.discord_content import official_pick_embed, best_two_embed
from jabazi.persistence.store import Store


def research_record(store):
    payload={
        "completed_at":"2026-09-29T13:58:00+00:00",
        "healthy":True,
        "rows":[
            {
                "sport":"basketball_nba","event_id":"nba1","event":"A @ B","market":"h2h",
                "selection":"B","book":"FanDuel","decimal_odds":"1.91",
                "price_time_utc":"2026-09-29T13:57:30+00:00",
                "starts_at_utc":"2026-09-29T23:00:00+00:00",
                "market_no_vig_probability":"0.52","research_probability":"0.57",
                "model_version":"nba-test","uncertainty":"0.02","probability_edge":"0.05",
                "status":"WATCH","reason":"test","price_stale":False,"executable":True,
            },
            {
                "sport":"icehockey_nhl","event_id":"nhl1","event":"C @ D","market":"h2h",
                "selection":"D","book":"DraftKings","decimal_odds":"2.05",
                "price_time_utc":"2026-09-29T13:57:30+00:00",
                "starts_at_utc":"2026-09-29T23:30:00+00:00",
                "market_no_vig_probability":"0.48","research_probability":None,
                "model_version":None,"uncertainty":None,"probability_edge":None,
                "status":"RESEARCH / NOT AN OFFICIAL PICK","reason":"market only",
                "price_stale":False,"executable":True,
            },
            {
                "sport":"basketball_nba","event_id":"nba1","event":"A @ B","market":"spreads",
                "selection":"B","book":"FanDuel","decimal_odds":"1.91",
                "price_time_utc":"2026-09-29T13:57:30+00:00",
                "starts_at_utc":"2026-09-29T23:00:00+00:00",
                "market_no_vig_probability":"0.50","research_probability":"0.54",
                "model_version":"nba-test","uncertainty":"0.02","probability_edge":"0.04",
                "status":"WATCH","reason":"test","price_stale":False,"executable":True,
            },
        ],
    }
    store.append("research_sheet","latest_scan",payload,"research-test")
    return store.list_records("research_sheet",1,entity="latest_scan")[0]


def test_daily_moneyline_is_frozen_once_and_moneyline_only():
    store=Store("sqlite:///:memory:",initialize=True)
    try:
        record=research_record(store)
        now=datetime(2026,9,29,14,0,tzinfo=UTC)  # 9 AM Central daylight time
        _,created=freeze_daily_moneyline(store,record,now=now)
        assert created is True
        _,created_again=freeze_daily_moneyline(store,record,now=now+timedelta(minutes=2))
        assert created_again is False
        daily=daily_moneyline(store,now=now)
        assert daily["payload"]["row_count"]==2
        assert {r["sport_label"] for r in daily["payload"]["rows"]}=={"NBA","NHL"}
        text=render_text(daily)
        assert "DAILY MONEYLINE CHEAT SHEET" in text
        assert "spreads" not in text.lower()
    finally:
        store.close()


def test_entitlement_expiry_controls_active_members():
    store=Store("sqlite:///:memory:",initialize=True)
    try:
        now=datetime(2026,9,29,14,tzinfo=UTC)
        set_entitlement(
            store,member_id="123",status="active",plan="monthly",provider="stripe",
            provider_ref="sub_1",expires_at=(now+timedelta(days=30)).isoformat(),now=now,
        )
        assert latest_entitlement(store,"123",now=now)["active"] is True
        assert 123 in active_members(store,now=now)
        assert latest_entitlement(store,"123",now=now+timedelta(days=31))["active"] is False
        assert 123 not in active_members(store,now=now+timedelta(days=31))
    finally:
        store.close()


def test_official_pick_renderer_fails_closed_without_cash_authority(monkeypatch):
    monkeypatch.setenv("JABAZI_UNIT_SIZE","30")
    payload={
        "decision":"BET_NOW","stake":"30","model_probability":"0.60",
        "probability_edge":"0.05","model_version":"v1","reason":"supported",
        "reliability":{"model_can_influence_cash":False},
        "price":{
            "event":"A @ B","selection":"B","line":None,"best_book":"FanDuel",
            "best_decimal":"1.91","consensus_probability":"0.55",
        },
    }
    assert official_pick_embed(payload) is None
    payload["reliability"].update(model_can_influence_cash=True, model_stage="PRODUCTION_APPROVED")
    now = datetime.now(UTC)
    payload["price"].update(executable=True, source_timestamp=now.isoformat(), observed_at=now.isoformat(), starts_at=(now+timedelta(hours=1)).isoformat())
    payload["maximum_playable_decimal"] = "1.90"
    assert official_pick_embed(payload)["title"].startswith("🟢 JABBAZI MAIN CARD")


def test_best_two_renderer_keeps_price_check_visible():
    candidate={
        "status":"PRICE CHECK","method":"distinct_event_product_with_bound_propagation",
        "requested_stake_units":"2","recommended_stake_units":None,
        "reasons":["Exact sportsbook combined quote required"],
        "legs":[
            {"event":"A @ B","selection":"B","line":None},
            {"event":"C @ D","selection":"D","line":None},
        ],
    }
    embed=best_two_embed(candidate)
    assert embed is not None
    assert any(f["value"]=="PRICE CHECK" for f in embed["fields"])


def test_discord_blueprint_has_unique_channels_and_required_sections():
    blueprint=json.loads(Path("docs/discord/server_blueprint.json").read_text())
    channels=[name for category in blueprint["categories"] for name in category["channels"]]
    assert len(channels)==len(set(channels))
    for required in (
        "daily-moneyline-cheat-sheet","jabbazi-main-card","best-two-parlay",
        "vip-access","scanner-status","support","staff-chat",
    ):
        assert required in channels
    assert any(role["name"]=="VIP" for role in blueprint["roles"])



def test_manual_vip_role_grants_member_app_access_without_billing_record():
    from jabazi.discord_bot import BotConfig, member_has_vip

    config = BotConfig(
        guild=1, owner=99, status_channel=2, sheets_channel=3,
        viewer_roles=frozenset(), vip_role=555,
    )
    member = SimpleNamespace(
        id=123,
        roles=[SimpleNamespace(id=555, name="VIP")],
    )
    assert member_has_vip(config, member) is True


def test_named_jabbazi_vip_role_is_backward_compatible():
    from jabazi.discord_bot import BotConfig, member_has_vip

    config = BotConfig(
        guild=1, owner=99, status_channel=2, sheets_channel=3,
        viewer_roles=frozenset(),
    )
    member = SimpleNamespace(
        id=123,
        roles=[SimpleNamespace(id=777, name="JABBAZI VIP")],
    )
    assert member_has_vip(config, member) is True


def test_simplified_blueprint_is_compact():
    blueprint=json.loads(Path("docs/discord/server_blueprint.json").read_text())
    channels=[name for category in blueprint["categories"] for name in category["channels"]]
    assert len(blueprint["categories"]) <= 7
    assert len(channels) <= 20
    vip_categories=[c for c in blueprint["categories"] if c["access"]=="vip"]
    assert {c["name"] for c in vip_categories} == {
        "━━ TODAY’S JABBAZI ━━", "━━ CHEAT SHEET ━━", "━━ VIP RESEARCH ━━"
    }



def test_custom_vip_named_role_grants_member_app_access():
    from jabazi.discord_bot import BotConfig, member_has_vip

    config = BotConfig(
        guild=1, owner=99, status_channel=2, sheets_channel=3,
        viewer_roles=frozenset(),
    )
    member = SimpleNamespace(
        id=123,
        roles=[SimpleNamespace(id=888, name="💎 JABBAZI GURU VIP ACCESS")],
    )
    assert member_has_vip(config, member) is True

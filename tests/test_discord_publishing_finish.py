from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

from jabazi.discord_bot import BotConfig, build_client
from jabazi.discord_content import performance_text
from jabazi.discord_observations import observations
from jabazi.performance import official_periods
from jabazi.persistence.store import Store


def test_research_updates_require_fresh_evidence_and_never_assign_stakes():
    now = datetime(2026, 9, 29, 16, tzinfo=UTC)
    row = {"sport": "baseball_mlb", "event_id": "game", "event": "Away @ Home", "market": "h2h", "selection": "Home",
           "starts_at_utc": (now+timedelta(hours=1)).isoformat(), "price_time_utc": now.isoformat(),
           "market_no_vig_probability": ".52", "research_probability": ".66", "decimal_odds": "2.1", "book": "Book",
           "executable": True, "data_health": "HEALTHY", "reason": "Independent model disagreement."}
    current = {"payload": {"healthy": True, "completed_at": now.isoformat(), "rows": [row, dict(row)]}}
    prior = {"payload": {"healthy": True, "completed_at": (now-timedelta(minutes=5)).isoformat(),
                         "rows": [row | {"market_no_vig_probability": ".48"}]}}
    research = observations([current, prior], lane="research", now=now)
    assert len(research) == 1 and "NOT A PICK" in research[0]["embed"]["title"]
    assert "no stake assigned" in research[0]["embed"]["footer"]["text"]
    assert len(observations([current, prior], lane="market", now=now)) == 1
    assert observations([current], lane="market", now=now) == []
    assert observations([current, prior], lane="market", now=now+timedelta(minutes=6)) == []
    prior["payload"]["rows"][0]["market_no_vig_probability"] = ".51"
    assert observations([current, prior], lane="market", now=now) == []
    current["payload"]["healthy"] = False
    assert observations([current], lane="research", now=now) == []


def test_results_periods_use_central_date_separate_parlays_and_exclude_user_bets():
    # UTC Sep 30 is still Sep 29 in Chicago.
    now = datetime(2026, 9, 30, 1, tzinfo=UTC)
    def position(key, day, parlay=False, origin="scanner"):
        return {"id": key, "state": "settled", "payload": {"betting_date": day, "parlay": parlay,
                "origin": origin, "stake": "30", "unit_size": "30"}}
    rows = [position("a", "2026-09-29"), position("b", "2026-09-28", True),
            position("c", "2026-09-20"), position("d", "2026-09-29", origin="user")]
    outcomes = {"a": {"profit": "-30", "result": "loss"}, "b": {"profit": "60", "result": "win"},
                "c": {"profit": "30", "result": "win"}, "d": {"profit": "9000", "result": "win"}}
    periods = official_periods(rows, outcomes, now)
    assert periods[0]["through"] == "2026-09-29"
    assert periods[0]["groups"][0]["roi"] == Decimal(-1)
    assert periods[0]["groups"][1]["settled"] == 0
    assert periods[1]["groups"][1]["profit_units"] == 2
    assert periods[2]["groups"][0]["profit_units"] == 0
    text = performance_text({"official_periods": periods})
    assert "CLV: unavailable" in text and "Today" in text and "This month" in text
    assert len(text) <= 1900 and "9000" not in text


def test_alert_delivery_cannot_ping_everyone_users_or_privileged_roles():
    db = Store("sqlite:///:memory:", initialize=True)
    client = build_client(BotConfig(1, 2, 3, 4, frozenset()), db)
    def role(key, name, permissions=0):
        return NS(id=key, name=name, permissions=NS(value=permissions), managed=False, position=1, mention=f"<@&{key}>")
    guild = NS(roles=[role(10, "Main Card Alerts"), role(11, "NFL Alerts", 8), role(12, "Other")], me=NS(top_role=NS(position=9)))
    client.get_guild = lambda _: guild
    result = client.alert_delivery("Main Card Alerts", "americanfootball_nfl")
    assert result["content"] == "<@&10>"
    assert result["allowed_mentions"].to_dict() == {"roles": [10], "parse": []}
    db.close()

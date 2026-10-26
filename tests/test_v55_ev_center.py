"""V5.5 +EV center: no invented edge, no unapproved bets, no stale prices."""
from datetime import UTC, datetime, timedelta

from jabazi.vip.ev_center import ev_center

NOW = datetime(2026, 10, 26, 16, tzinfo=UTC)


def row(**changes):
    r = {
        "id": "candidate-1", "sport": "NBA", "event_id": "game-1",
        "event": "Away @ Home", "starts_at": (NOW + timedelta(hours=3)).isoformat(),
        "price_at": NOW.isoformat(), "lifecycle": "UPCOMING", "status": "WATCH",
        "fresh": True, "data_health": "HEALTHY", "market": "player_points",
        "player": "Player One", "selection": "Over", "line": 24.5,
        "decimal": 2.0, "book": "DraftKings",
        "model_probability": .57, "calibrated_probability": .56,
        "market_probability": .51, "model_stage": "PRODUCTION_APPROVED",
        "model_version": "validated-v1",
    }
    return {**r, **changes}


def test_model_ev_uses_calibrated_probability_and_correct_math():
    result = ev_center([row()], now=NOW, min_ev=.03)
    assert result["matching"] == 1
    item = result["rows"][0]
    assert abs(item["ev"] - .12) < 1e-9
    assert abs(item["expected_profit_per_50"] - 6) < 1e-9
    assert abs(item["fair_decimal"] - 1 / .56) < 1e-9
    assert item["status"] == "WATCH"
    assert item["approved_for_betting"] is False


def test_unapproved_stale_unhealthy_and_missing_price_fail_closed():
    rows = [
        row(id="shadow", model_stage="SHADOW_ONLY"),
        row(id="stale", price_at=(NOW-timedelta(minutes=6)).isoformat()),
        row(id="bad", data_health="DEGRADED"),
        row(id="no-book", book=None),
        row(id="expired", starts_at=(NOW-timedelta(minutes=1)).isoformat()),
        row(id="invalid", model_probability=1.5, calibrated_probability=None),
    ]
    result = ev_center(rows, now=NOW)
    assert result["matching"] == 0


def test_filters_and_sorting_do_not_change_approval():
    rows = [
        row(id="a", book="DraftKings", decimal=2.0),
        row(id="b", book="FanDuel", decimal=2.3),
        row(id="c", sport="NFL", decimal=3.0),
    ]
    result = ev_center(rows, now=NOW, sport="NBA", market="player_points", book="FanDuel")
    assert [x["id"] for x in result["rows"]] == ["b"]
    result = ev_center(rows, now=NOW, sport="NBA")
    assert [x["id"] for x in result["rows"]] == ["b", "a"]
    assert not any(x["approved_for_betting"] for x in result["rows"])


def test_push_probability_is_accounted_for():
    result = ev_center([row(model_probability=.5, calibrated_probability=.5,
                            push_probability=.1, decimal=2.0)], now=NOW)
    assert abs(result["rows"][0]["ev"] - .1) < 1e-9


def test_no_fabricated_market_based_ev_when_model_unavailable():
    result = ev_center([row(model_probability=None, calibrated_probability=None,
                            market_probability=.75)], now=NOW)
    assert not result["rows"]


def test_ui_exposes_six_primary_destinations_and_ev_filters():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src/jabazi/static"
    html = (root / "terminal.html").read_text()
    js = (root / "terminal.js").read_text()
    assert html.count('<nav id="navigation"') == 1
    for href in ('#home', '#top10&sport=NBA', '#ev', '#board', '#sheets', '#more'):
        assert f'href="{href}"' in html
    assert "else if(route==='ev')" in js
    assert "Minimum estimated EV" in js
    assert "No qualified +EV research" in js


def test_ev_endpoint_does_not_expose_research_without_vip_context():
    from fastapi.testclient import TestClient
    from jabazi.api import app

    response = TestClient(app).get("/v1/vip/ev-center?min_ev=3")
    assert response.status_code in (401, 403, 503)
    assert "expected_profit_per_50" not in response.text


def test_invalid_ev_query_does_not_expose_any_private_data():
    from fastapi.testclient import TestClient
    from jabazi.api import app

    response = TestClient(app).get("/v1/vip/ev-center?min_ev=1000")
    # The test environment can reject unavailable DB access before validation.
    assert response.status_code in (422, 503)
    assert "expected_profit_per_50" not in response.text


def test_invalid_threshold_rejected_by_research_engine():
    import pytest
    with pytest.raises(ValueError):
        ev_center([row()], now=NOW, min_ev=10)

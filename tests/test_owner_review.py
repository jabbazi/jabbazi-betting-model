from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.owner_review import review_snapshot
from jabazi.persistence.store import Store

NOW = datetime(2026, 9, 23, tzinfo=UTC)


@pytest.fixture
def store():
    value = Store("sqlite:///:memory:", initialize=True)
    yield value
    value.close()


def add(store, **changes):
    row = {
        "sport": "americanfootball_nfl",
        "event": "<script>alert(1)</script>",
        "research_probability": "0.7",
        "model_version": None,
        "probability_edge": "0.1",
        "expected_roi": "0.2",
        "market_no_vig_probability": "0.6",
        "price_time_utc": (NOW - timedelta(minutes=10)).isoformat(),
    }
    payload = {"completed_at": NOW.isoformat(), "healthy": True, "rows": [row]} | changes
    store.append("research_sheet", "latest_scan", payload)


def test_no_model_cannot_inherit_market_probability_or_edge(store):
    add(store)
    result = review_snapshot(store, now=NOW)
    card = result["cards"][0]
    assert card["research_probability"] is None
    assert card["market_no_vig_probability"] == "0.6"
    assert card["expected_roi"] is None and card["probability_edge"] is None
    assert card["decision"] == "WATCH" and card["stake"] is None
    assert any("fresh" in blocker for blocker in card["blockers"])
    assert result["betting_enabled"] is False


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"healthy": False}, "DATA_UNHEALTHY"),
        ({"completed_at": (NOW - timedelta(hours=4)).isoformat()}, "STALE_DATA"),
        ({"completed_at": (NOW + timedelta(seconds=1)).isoformat()}, "STALE_DATA"),
        ({"completed_at": "bad"}, "STALE_DATA"),
    ],
)
def test_latest_bad_snapshot_not_presented_as_current(store, changes, status):
    add(store, **changes)
    assert review_snapshot(store, now=NOW)["status"] == status


def test_pagination_and_sport_filter(store):
    rows = [{"sport": "americanfootball_nfl", "selection": str(i)} for i in range(28)]
    add(store, rows=rows + [{"sport": "baseball_mlb"}])
    result = review_snapshot(store, now=NOW, sport="nfl", page=2)
    assert result["total"] == 28
    assert [r["selection"] for r in result["cards"]] == ["25", "26", "27"]


def test_private_data_auth_and_no_cache(store, monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    client = TestClient(app)
    with patch("jabazi.api.platform_store") as factory:
        assert client.get("/v1/owner/review").status_code == 401
        factory.assert_not_called()
    add(store)
    with patch("jabazi.api.platform_store", return_value=store), patch.object(store, "close"):
        headers = {"Authorization": "Bearer " + "x" * 32}
        response = client.get("/v1/owner/review", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/v1/owner/review?page=0", headers=headers).status_code == 422
        assert client.get("/v1/owner/review?sport=invalid", headers=headers).status_code == 422
    html = client.get("/owner")
    assert "frame-ancestors" in html.headers["content-security-policy"]
    assert "<script>alert" not in html.text
    js = client.get("/owner/review.js").text
    assert "innerHTML" not in js and "localStorage" not in js and "sessionStorage" not in js

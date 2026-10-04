from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.automation import AutomaticScanner
from jabazi.config import Settings
from jabazi.domain.health import assess, allowed_market
from jabazi.domain.models import DataQuality, Decision, Quote
from jabazi.domain.shopping import build_price_cards
from jabazi.persistence.store import Store
from jabazi.persistence.factory import ledger
from jabazi.providers.base import ProviderBatch


def quotes():
    now = datetime.now(UTC)
    return tuple(
        Quote(
            str(i),
            "event",
            "h2h",
            side,
            book,
            D(price),
            None,
            now,
            now,
            DataQuality.REALTIME,
            "americanfootball_nfl",
            "B @ A",
            now + timedelta(hours=2),
        )
        for i, (book, side, price) in enumerate(
            [
                ("draftkings", "A", "2.1"),
                ("draftkings", "B", "1.8"),
                ("fanduel", "A", "2.05"),
                ("fanduel", "B", "1.85"),
            ]
        )
    )


def test_health_gates_and_louisiana_allowlist():
    now = datetime.now(UTC)
    result = assess(
        now=now,
        observed_at=now,
        source_at=now - timedelta(minutes=5),
        starts_at=now + timedelta(hours=2),
        model_approved=True,
        database_ok=True,
        lineup_ready=False,
        calibration_drift=True,
    )
    assert not result.healthy
    assert set(result.reasons) == {"STALE_DATA", "WAIT_FOR_LINEUP", "CALIBRATION_DRIFT"}
    assert not allowed_market("americanfootball_ncaaf", "player_anytime_td")
    assert not allowed_market("americanfootball_ncaaf", "new_unknown_prop")
    assert allowed_market("americanfootball_ncaaf", "spreads_h1")


def test_stale_and_outlier_books_cannot_supply_best_price():
    base = quotes()
    now = datetime.now(UTC)
    old = tuple(
        replace(
            q, sportsbook="old", decimal_odds=D(10), source_timestamp=now - timedelta(minutes=5)
        )
        for q in base[:2]
    )
    outlier = (
        replace(base[0], sportsbook="outlier", decimal_odds=D(20)),
        replace(base[1], sportsbook="outlier", decimal_odds=D("1.05")),
    )
    cards = build_price_cards(base + old + outlier, now=now)
    assert cards
    assert all("old" not in c.book_prices and "outlier" not in c.book_prices for c in cards)
    assert all(c.executable for c in cards)


def test_three_way_consensus_is_a_probability_distribution():
    q = quotes()[0]
    all_quotes = []
    for book, prices in [
        ("a", ["2", "3", "4"]),
        ("b", ["2.2", "2.8", "4"]),
        ("c", ["1.9", "3.5", "4"]),
    ]:
        all_quotes.extend(
            replace(
                q,
                sport="soccer_epl",
                sportsbook=book,
                selection_key=side,
                decimal_odds=D(price),
                provider_quote_id=book + side,
            )
            for side, price in zip(["A", "Draw", "B"], prices)
        )
    cards = build_price_cards(tuple(all_quotes))
    assert len(cards) == 3
    assert abs(sum(c.consensus_probability for c in cards) - 1) < D("1e-25")


def test_production_refuses_local_database(monkeypatch, tmp_path):
    monkeypatch.setenv("JABAZI_ENV", "production")
    monkeypatch.delenv("JABBAZI_PLATFORM_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        ledger(str(tmp_path / "old.db"))
    assert TestClient(app).get("/readyz").status_code == 503
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(RuntimeError):
        ledger(str(tmp_path / "old.db"))


def test_api_authentication_readiness_and_real_database_round_trip(monkeypatch, tmp_path):
    url = "sqlite:///" + str(tmp_path / "platform.db")
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "x" * 32)
    s = Store(url, initialize=True)
    s.append("candidate", "test", {"status": "WATCH"})
    s.close()
    client = TestClient(app)
    assert client.get("/v1/candidates").status_code == 401
    response = client.get("/v1/candidates", headers={"Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 200
    assert response.json()["records"][0]["payload"]["status"] == "WATCH"
    assert client.get("/readyz").json()["betting_enabled"] is False
    assert (
        client.get(
            "/v1/candidates?limit=1001", headers={"Authorization": "Bearer " + "x" * 32}
        ).status_code
        == 422
    )


def test_provider_error_cancels_reservation_and_only_persists_watch(tmp_path):
    url = "sqlite:///" + str(tmp_path / "platform.db")
    s = Store(url, initialize=True)
    batch = ProviderBatch(
        "TEST_ONLY", datetime.now(UTC), b'{"test":true}', quotes(), requests_remaining=100
    )
    estimate = SimpleNamespace(
        probability=D(".70"),
        uncertainty=D(".01"),
        approved_for_betting=True,
        model_version="SYNTHETIC_TEST_ONLY",
        feature_snapshot={"production_inputs_verified": True},
    )
    model = SimpleNamespace(estimate=lambda card: estimate)
    with (
        patch("jabazi.automation.Ledger", return_value=s),
        patch("jabazi.automation.load_models", return_value=({"americanfootball_nfl": model}, [])),
        patch("jabazi.automation.TheOddsApiProvider") as provider,
        patch.object(
            AutomaticScanner,
            "_active_supported",
            return_value=[{"key": "americanfootball_nfl"}, {"key": "baseball_mlb"}],
        ),
    ):
        provider.return_value.fetch.side_effect = [batch, RuntimeError("provider test failure")]
        result = AutomaticScanner(Settings.from_environment()).run()
    assert result.errors
    assert all(a.decision != Decision.BET_NOW for a in result.actions)
    check = Store(url)
    assert check.open_exposure() == 0
    assert all(r["payload"]["decision"] != "BET_NOW" for r in check.list_records("candidate"))
    assert check.list_records("scan_run")[0]["payload"]["healthy"] is False
    check.close()

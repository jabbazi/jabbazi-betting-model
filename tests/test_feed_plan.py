import json
from datetime import UTC, datetime, timedelta

from jabazi.feed_plan import FeedPlan
from jabazi.persistence.store import Store
from jabazi.providers.base import ProviderBatch

NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)
SPORTS = [{"key": s} for s in ("americanfootball_nfl", "baseball_mlb", "americanfootball_ncaaf")]


def factory(calls, base_now=NOW):
    class Provider:
        def __init__(self, sport, markets):
            self.sport, self.markets = sport, markets

        def batch(self, event=None):
            events = [
                {
                    "id": self.sport + str(i),
                    "away_team": "Away",
                    "home_team": "Home",
                    "commence_time": (base_now + timedelta(hours=8 + i)).isoformat(),
                    "bookmakers": [{"key": "synthetic"}],
                }
                for i in range(2)
            ]
            raw = next(e for e in events if e["id"] == event) if event else events
            return ProviderBatch(
                "TEST_ONLY", base_now, json.dumps(raw).encode(), (), requests_remaining=10000
            )

        def fetch(self):
            calls.append((self.sport, None, self.markets))
            return self.batch()

        def fetch_event(self, event, markets):
            calls.append((self.sport, event, markets))
            return self.batch(event)

    return Provider


def test_event_feeds_preserve_primary_coverage_and_budget_then_rotate_events_and_markets(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "scan.db"), initialize=True)
    calls, errors = [], []
    try:
        for round in range(3):
            plan = FeedPlan(
                factory(calls),
                store,
                15,
                50,
                errors,
                lambda: True,
                now=NOW + timedelta(minutes=round),
            )
            batches = list(plan.batches(SPORTS))
            assert len(batches) == 5 and plan.spent == 15
            assert plan.coverage["event_requests"] == 2
            assert all(r["partial"] for r in plan.coverage["sports"].values())
        assert not errors
        assert all(c[1] is None for c in calls[:3])
        assert calls[3][1].endswith("0") and calls[4][1].endswith("0")
        assert calls[8][1].endswith("1") and calls[9][1].endswith("1")
        assert calls[13][1].endswith("0")
        assert calls[13][2][0] == "player_anytime_td"
        assert set(calls[13][2][1:]) == {"player_receptions", "player_pass_tds"}
        assert not any(s == "americanfootball_ncaaf" and e for s, e, _ in calls)
    finally:
        store.close()


def test_weekend_event_budget_prioritizes_nfl_and_always_requests_atd(tmp_path, monkeypatch):
    saturday = datetime(2026, 9, 26, 12, tzinfo=UTC)
    monkeypatch.setenv("JABBAZI_MONTHLY_CREDIT_LIMIT", "10000")
    monkeypatch.setenv("JABBAZI_WEEKEND_NFL_EVENT_PRIORITY", "true")
    store = Store("sqlite:///" + str(tmp_path / "weekend.db"), initialize=True)
    calls, errors = [], []
    try:
        plan = FeedPlan(
            factory(calls, saturday),
            store,
            30,
            50,
            errors,
            lambda: True,
            now=saturday,
        )
        list(plan.batches(SPORTS))
        event_calls = [call for call in calls if call[1] is not None]
        nfl_calls = [call for call in event_calls if call[0] == "americanfootball_nfl"]
        mlb_calls = [call for call in event_calls if call[0] == "baseball_mlb"]
        assert nfl_calls
        assert all("player_anytime_td" in markets for _, _, markets in nfl_calls)
        # Synthetic fixture has only two NFL events; weekend priority exhausts
        # those before allocating remaining deep-market requests to MLB.
        assert [event for _, event, _ in event_calls[:2]] == [
            "americanfootball_nfl0",
            "americanfootball_nfl1",
        ]
        assert mlb_calls
    finally:
        store.close()


def test_monthly_limit_blocks_additional_provider_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("JABBAZI_MONTHLY_CREDIT_LIMIT", "9")
    store = Store("sqlite:///" + str(tmp_path / "limit.db"), initialize=True)
    calls, errors = [], []
    try:
        plan = FeedPlan(factory(calls), store, 15, 50, errors, lambda: True, now=NOW)
        list(plan.batches(SPORTS))
        assert len(calls) == 3 and plan.spent == 9
        assert errors == ["MONTHLY_QUOTA_LIMIT"]
        assert plan.coverage["stop_reason"] == "MONTHLY_QUOTA_LIMIT"
    finally:
        store.close()


def test_disabled_or_exhausted_event_budget_never_requests_props(monkeypatch):
    for disabled, budget in [(False, 9), (True, 15)]:
        monkeypatch.setenv("JABBAZI_EVENT_ODDS_ENABLED", "false" if disabled else "true")
        calls, errors = [], []
        plan = FeedPlan(factory(calls), None, budget, 50, errors, lambda: True, now=NOW)
        list(plan.batches(SPORTS))
        assert len(calls) == 3 and all(e is None for _, e, _ in calls)
        assert plan.coverage["event_requests"] == 0 and not errors


def test_prop_feed_reaches_archive_and_member_shortlist_without_fabricated_model(
    tmp_path, monkeypatch
):
    from dataclasses import replace
    from decimal import Decimal
    from jabazi.automation import AutomaticScanner
    from jabazi.config import Settings
    from jabazi.discord_sheets import archive_sheets, latest_sheet
    from jabazi.domain.models import DataQuality, Quote, Decision
    from jabazi.sheet_images import shortlist_rows

    now = datetime.now(UTC)
    url = "sqlite:///" + str(tmp_path / "integrated.db")
    Store(url, initialize=True).close()
    monkeypatch.setenv("JABBAZI_PLATFORM_DATABASE_URL", url)
    monkeypatch.setenv("JABBAZI_MONTHLY_CREDIT_LIMIT", "3000")
    monkeypatch.setenv("JABBAZI_WEEKEND_NFL_EVENT_PRIORITY", "false")
    monkeypatch.setattr("jabazi.automation.load_models", lambda _: ({}, []))
    monkeypatch.setattr(AutomaticScanner, "_active_supported", lambda _: SPORTS)

    class Provider:
        def __init__(self, sport, **kwargs):
            self.sport = sport
            self.event = {
                "id": sport,
                "away_team": "Synthetic Away",
                "home_team": "Synthetic Home",
                "commence_time": (now + timedelta(hours=3)).isoformat(),
                "bookmakers": [{"key": "test"}],
            }

        def fetch(self):
            return ProviderBatch(
                "TEST_ONLY", now, json.dumps([self.event]).encode(), (), requests_remaining=10000
            )

        def fetch_event(self, event_id, markets):
            market = markets[0]
            quotes = tuple(
                Quote(
                    f"{event_id}-{book}-{side}",
                    event_id,
                    market,
                    "Synthetic Player|" + side,
                    book,
                    Decimal("1.91"),
                    Decimal("4.5"),
                    now,
                    now,
                    DataQuality.REALTIME,
                    self.sport,
                    "Synthetic Away @ Synthetic Home",
                    now + timedelta(hours=3),
                )
                for book in ("draftkings", "fanduel")
                for side in ("Over", "Under")
            )
            return ProviderBatch(
                "TEST_ONLY", now, json.dumps(self.event).encode(), quotes, requests_remaining=10000
            )

    monkeypatch.setattr("jabazi.automation.TheOddsApiProvider", Provider)
    result = AutomaticScanner(
        replace(Settings.from_environment(), api_key="test-only"), max_credits_per_run=15
    ).run()
    assert not result.errors and result.feeds_scanned == 5
    assert result.event_market_coverage["event_requests"] == 2
    assert len(result.actions) == 4 and all(a.model_probability is None for a in result.actions)
    assert all(a.decision != Decision.BET_NOW and not a.stake for a in result.actions)
    store = Store(url)
    try:
        archive_sheets(store, result)
        record = latest_sheet(store)
        for sport, group in (("nfl", 2), ("mlb", 1)):
            rows = shortlist_rows(record, sport, group)
            assert len(rows) == 1 and rows[0]["participant"] == "Synthetic Player"
            assert rows[0]["best"] is None and rows[0]["edge"] is None
            assert rows[0]["reference"]["market_no_vig_probability"] == "0.5"
    finally:
        store.close()


def test_nhl_base_and_derivative_feeds_respect_existing_budget():
    calls, errors = [], []
    plan = FeedPlan(factory(calls), None, 15, 50, errors, lambda: True, now=NOW)
    result = list(plan.batches(SPORTS + [{"key": "icehockey_nhl"}]))
    assert len(result) == 5 and plan.spent == 15
    assert {s for s,e,m in calls if e is None} == {r["key"] for r in SPORTS} | {"icehockey_nhl"}
    plan = FeedPlan(factory(calls), None, 9, 50, errors, lambda: True, now=NOW)
    list(plan.batches([{"key": "icehockey_nhl"}]))
    assert plan.spent <= 9 and not errors
    event_calls = [(s, e, m) for s, e, m in calls if s == "icehockey_nhl" and e]
    assert event_calls
    assert any("player_shots_on_goal" in markets for _, _, markets in event_calls)
    assert any(any(market.startswith("player_") for market in markets)
               for _, _, markets in event_calls)

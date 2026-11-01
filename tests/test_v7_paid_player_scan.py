"""V7 unit/integration fixtures; NOT live subscription or calibration evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import log
from types import SimpleNamespace

import pytest

from jabazi.boost_goat_inference_acceptance import audit_exact_line_research
from jabazi.boost_identity_manifest import crosswalk_digest
from jabazi.boost_scope import SPORTS
from jabazi.models.player_distribution import calibrated_probability
from jabazi.paid_player_scan import (
    BoundedPages, PaidScanLimits, RequestBudget, present_paid_scan,
    read_saved_paid_scan, run_paid_player_scan, stored_evidence, vip_research_rows,
)
from jabazi.player_probability_board import from_scan_actions
from jabazi.providers.balldontlie import BallDontLieError
from jabazi.research.player_features import REQUIRED_INTEGRITY

NOW = datetime(2026, 11, 1, 20, tzinfo=UTC)
START = NOW + timedelta(hours=3)
MARKETS = {"NBA": ("points", "player_points", 20.5, 20),
           "NFL": ("receptions", "player_receptions", 4.5, 5),
           "NHL": ("goals", "player_goals", 1, .5)}


class MemoryStore:
    def __init__(self, *, max_charges=1000):
        self.records, self.charges = [], []
        self.max_charges = max_charges

    def list_records(self, kind, limit, entity=None):
        return [deepcopy(r) for r in reversed(self.records)
                if r["kind"] == kind and (entity is None or r["entity"] == entity)][:limit]

    def append(self, kind, entity, payload, key):
        if any(r["id"] == key for r in self.records):
            return False
        self.records.append({"kind": kind, "entity": entity,
                             "payload": deepcopy(payload), "id": key})
        return True

    def claim_credits(self, provider, amount, *, monthly_limit, key):
        if len(self.charges) >= min(monthly_limit, self.max_charges):
            return False
        self.charges.append((provider, amount, key))
        return True


def evidence(sport):
    namespace = {"NBA": "ESPN", "NFL": "NFLVERSE", "NHL": "NHL"}[sport]
    _, market, _, mean = MARKETS[sport]
    mapping = {"sport": sport, "bdl_game_id": 77, "bdl_player_id": 19,
               "source_namespace": namespace, "source_player_id": f"SOURCE_{sport}",
               "source_record_sha256": "a" * 64, "canonical_event_id": f"EVENT_{sport}",
               "event_starts_at": START.isoformat(), "team_id": "TEAM",
               "reviewed_at": (NOW - timedelta(minutes=15)).isoformat(),
               "independent_source_reviewed": True}
    mapping["record_sha256"] = crosswalk_digest(mapping)
    snapshot = {"sport": SPORTS[sport], "event_id": f"EVENT_{sport}",
                "player_id": f"SOURCE_{sport}", "market": market, "participant": f"Fixture {sport}",
                "starts_at": START.isoformat(),
                "features_available_at": (NOW - timedelta(minutes=2)).isoformat(),
                "snapshot_id": "playerfs-" + "b" * 20, "source_checksum": "c" * 64,
                "provider": namespace, "feature_schema_version": "fixture",
                "research_only": False, "production_inputs_verified": True,
                "integrity": {name: True for name in REQUIRED_INTEGRITY},
                "features": {"games_prior": 10.0}}
    artifact = {"sport": SPORTS[sport], "market": market,
                "artifact_type": "player_prop_distribution", "stage": "VALIDATING",
                "model_version": f"fixture-{sport}-v1", "family": "count_nb",
                "feature_names": ["games_prior"], "scaler": {"mean": [0], "scale": [1]},
                "parameters": {"coef": [0], "intercept": log(mean), "dispersion": .2},
                "calibration": None, "validation": {"promotion_passed": False}}
    return mapping, snapshot, artifact


def seed(store, sports=("NBA", "NFL", "NHL"), *, mappings=True):
    models = {}
    for sport in sports:
        mapping, snapshot, artifact = evidence(sport)
        if mappings:
            store.append("paid_player_identity_manifest", sport, {"records": [mapping]}, sport + "-map")
        store.append("player_feature_snapshot", sport, snapshot, sport + "-features")
        models[(SPORTS[sport], artifact["market"])] = SimpleNamespace(artifact=artifact)
    return models


def quote(sport, **changes):
    market, _, line, _ = MARKETS[sport]
    row = {"id": 100, "game_id": 77, "player_id": 19, "vendor": "fixture_book",
           "prop_type": market, "line_value": line,
           "market": {"type": "milestone", "odds": 110} if sport == "NHL" else
                     {"type": "over_under", "over_odds": -110, "under_odds": -110},
           "updated_at": (NOW - timedelta(seconds=30)).isoformat()}
    row.update(changes)
    return row


def game(sport, start=START, **changes):
    row = {"id": 77, "status_state": "scheduled", "date": start.isoformat(),
           "datetime": start.isoformat(), "game_date": start.date().isoformat(),
           "start_time_utc": start.isoformat(), "home_team": {"full_name": "Fixture Home"},
           "visitor_team": {"full_name": "Fixture Away"}}
    row.update(changes)
    return row


class PaidProvider:
    def __init__(self, *, errors=None, paginate=False, empty=False, games=None):
        self.calls, self.closed = [], False
        self.errors, self.paginate, self.empty, self.games = errors or {}, paginate, empty, games

    def fetch(self, sport, resource, params):
        self.calls.append((sport, resource, list(params)))
        if sport in self.errors:
            raise BallDontLieError(self.errors[sport])
        if resource == "games":
            return {"data": [game(sport.upper())] if self.games is None else self.games, "meta": {}}
        cursor = dict(params).get("cursor")
        rows = [] if self.empty else [quote(sport.upper(), vendor="second_book" if cursor else "fixture_book")]
        return {"data": rows, "meta": {"next_cursor": 2 if self.paginate and cursor is None else None}}

    def close(self):
        self.closed = True


def no_lab(key, sport, day, *, request_guard):
    # No key implies no request. Unsupported NHL must not trigger LAB requests.
    return {"rows": [], "coverage_complete": False, "state": "UNAVAILABLE",
            "reason": "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED" if sport == "NHL" else "NO_CREDENTIAL",
            "model_hit_probabilities_verified": False, "betting_enabled": False}


def run(*, provider=None, store=None, sports=("NBA", "NFL", "NHL"), mappings=True,
        limits=None, lab_reader=no_lab, lab_key=""):
    store = store or MemoryStore()
    models = seed(store, sports, mappings=mappings)
    provider = provider or PaidProvider()
    limits = limits or PaidScanLimits(requests=30, seconds=60, interval=0)
    result = run_paid_player_scan(
        store, SimpleNamespace(balldontlie_api_key="PRIVATE_KEY", balldontlie_lab_api_key=lab_key),
        models, lambda: True, now=NOW, limits=limits, sports=sports,
        provider_factory=lambda key, **kw: provider, lab_reader=lab_reader,
    )
    return result, store, provider


def test_all_three_real_adapter_paths_emit_fitted_research_not_price_probabilities():
    report, store, provider = run(provider=PaidProvider(paginate=True))
    assert provider.closed
    assert report["paid_requests_made"] == 9
    assert len(store.charges) == 9
    assert report["collection_complete"] and report["model_scope_complete"]
    assert report["scope_complete"]
    assert report["status"] == "RESEARCH_SCOPE_COMPLETE"
    assert report["betting_enabled"] is False
    assert report["joint_calibration_validated"] is False
    assert report["full_market_entitlement_verified"] is False
    for sport, row in report["sports"].items():
        assert row["coverage"] == "FULL"
        assert row["accepted_quotes"] == 2 and row["pages"] == 3
        assert row["inference"]["exact_line_research_estimates"] == 2
        assert row["research_rows"]
        for estimate in row["research_rows"]:
            assert estimate["model_version"] == f"fixture-{sport}-v1"
            assert estimate["model_stage"] == "VALIDATING"
            assert estimate["approved_for_betting"] is False
            assert estimate["calibration_verified"] is False
            assert 0 < estimate["model_probability"] < 1
            assert estimate["event"] == "Fixture Away @ Fixture Home"
            assert "PRIVATE_KEY" not in str(estimate)
    assert len(store.list_records("paid_player_quote_snapshot", 10)) == 3
    assert store.list_records("paid_player_scan", 1, entity="2026-11-01")


def test_nhl_one_plus_goals_uses_at_least_one_not_over_one():
    report, _, _ = run(sports=("NHL",))
    row = report["sports"]["NHL"]["research_rows"][0]
    _, features, model = evidence("NHL")
    expected = calibrated_probability(model, features["features"], "over", Decimal("0.5"))
    assert row["line"] == "1" and row["model_threshold"] == "0.5"
    assert row["settlement"] == "AT_LEAST"
    assert row["model_probability"] == pytest.approx(expected)
    assert row["model_probability"] != pytest.approx(1 / row["best_decimal"])


def test_nhl_whole_number_over_under_is_not_reinterpreted_as_milestone():
    mapping, snap, model = evidence("NHL")
    offer = quote("NHL", market={"type": "over_under", "over_odds": 110, "under_odds": -120})
    r = audit_exact_line_research("NHL", [{"sport": SPORTS["NHL"], "raw": offer}],
                                 [mapping], [snap], [model], observed_at=NOW)
    assert r["status"] == "UNAVAILABLE"
    assert r["rejections"]["EXACT_LINE_MODEL_INFERENCE_UNAVAILABLE"] == 1


def test_missing_identity_keeps_quotes_but_cannot_claim_model_complete():
    report, _, _ = run(mappings=False)
    assert report["collection_complete"] is True
    assert report["model_scope_complete"] is False and report["scope_complete"] is False
    assert report["status"] == "PARTIAL"
    for row in report["sports"].values():
        assert row["accepted_quotes"] == 1 and row["research_rows"] == []
        assert row["rejections"]["MISSING_OR_AMBIGUOUS_CROSSWALK"] == 1


def test_partial_prop_page_is_retained_without_false_complete():
    report, _, _ = run(provider=PaidProvider(paginate=True), sports=("NBA",),
                       limits=PaidScanLimits(requests=10, seconds=60, interval=0, prop_pages=1))
    row = report["sports"]["NBA"]
    assert row["accepted_quotes"] == 1 and row["research_rows"]
    assert row["coverage"] == "PARTIAL" and report["scope_complete"] is False
    assert "PAGINATION_LIMIT_REACHED" in row["errors"]


def test_empty_props_are_not_complete_even_http_200_and_complete_cursor():
    report, _, _ = run(provider=PaidProvider(empty=True))
    assert report["scope_complete"] is False
    assert all("EMPTY_ELIGIBLE_GAME_PROPS" in r["errors"] for r in report["sports"].values())


def test_nhl_401_does_not_erase_independent_nba_nfl_results():
    report, _, provider = run(provider=PaidProvider(errors={"nhl": "HTTP_401"}))
    assert report["sports"]["NBA"]["research_rows"]
    assert report["sports"]["NFL"]["research_rows"]
    assert report["sports"]["NHL"]["coverage"] == "FAILED"
    assert "GAME_DISCOVERY:HTTP_401" in report["sports"]["NHL"]["errors"]
    assert len([c for c in provider.calls if c[0] == "nhl"]) == 1
    assert not report["scope_complete"]


def test_429_stops_shared_provider_calls_without_retry_storm():
    report, _, provider = run(provider=PaidProvider(errors={"nba": "HTTP_429"}))
    assert len(provider.calls) == 1
    assert report["paid_requests_made"] == 1
    assert report["stop_reason"] == "HTTP_429"
    assert not report["scope_complete"]


def test_sport_only_mode_does_not_fetch_other_sports():
    report, _, provider = run(sports=("NHL",))
    assert report["scope"] == ["NHL"]
    assert {c[0] for c in provider.calls} == {"nhl"}
    assert set(report["sports"]) == {"NHL"}


def test_monthly_ceiling_stops_before_unreserved_network_calls():
    report, store, provider = run(store=MemoryStore(max_charges=1))
    assert len(store.charges) == len(provider.calls) == report["paid_requests_made"] == 1
    assert report["stop_reason"] == "MONTHLY_REQUEST_LIMIT"
    assert not report["scope_complete"]


def test_lab_signals_are_archived_separately_never_become_hit_chances():
    def lab(key, sport, day, *, request_guard):
        if sport == "NHL":
            return no_lab(key, sport, day, request_guard=request_guard)
        request_guard()
        return {"rows": [{"provider_confidence_raw": .99, "model_signal_value": 99,
                          "player_name": "LAB_PRIVATE"}], "coverage_complete": True,
                "model_hit_probabilities_verified": False, "betting_enabled": False}
    report, store, _ = run(lab_reader=lab, lab_key="PRIVATE_LAB_KEY")
    assert report["paid_requests_made"] == 8
    assert len(store.list_records("paid_lab_signal_snapshot", 10)) == 2
    assert "LAB_PRIVATE" not in str(report)
    assert "PRIVATE_LAB_KEY" not in str(report)
    assert all("rows" not in row["lab"] for row in report["sports"].values())
    assert all(r["model_probability"] != .99 for row in report["sports"].values() for r in row["research_rows"])


def test_unexpected_lab_failure_preserves_paid_quotes_and_marks_incomplete():
    def broken_lab(*args, **kw):
        raise ValueError("PRIVATE_KEY/provider/raw/secret")
    report, _, _ = run(lab_reader=broken_lab, lab_key="configured")
    assert report["sports"]["NBA"]["research_rows"]
    assert report["lab_scope_complete"] is False
    assert "PRIVATE_KEY" not in str(report)


def test_storage_and_explicit_opt_out_precede_provider_construction(monkeypatch):
    def forbidden(*args, **kw):
        raise AssertionError("unexpected provider")
    settings = SimpleNamespace(balldontlie_api_key="configured", balldontlie_lab_api_key="")
    result = run_paid_player_scan(None, settings, {}, lambda: True, provider_factory=forbidden)
    assert result["reason"] == "DURABLE_STORAGE_REQUIRED"
    monkeypatch.setenv("JABBAZI_PAID_PLAYER_SCAN_ENABLED", "false")
    result = run_paid_player_scan(MemoryStore(), settings, {}, lambda: True, provider_factory=forbidden)
    assert result["requested"] is False and result["status"] == "DISABLED"


def test_missing_keys_do_not_construct_provider_or_fake_success():
    def forbidden(*args, **kw):
        raise AssertionError("unexpected provider")
    result = run_paid_player_scan(MemoryStore(), SimpleNamespace(balldontlie_api_key="", balldontlie_lab_api_key=""),
                                  {}, lambda: True, now=NOW, provider_factory=forbidden, lab_reader=no_lab)
    assert result["paid_requests_made"] == 0 and not result["scope_complete"]
    assert all(row["errors"] == ["SPORTS_API_KEY_NOT_CONFIGURED"] for row in result["sports"].values())


@pytest.mark.parametrize("scope", [(), ("NBA", "NBA"), ("WNBA",), ("NBA", "unsupported")])
def test_invalid_sport_scope_rejected_before_access(scope):
    with pytest.raises(ValueError):
        run_paid_player_scan(MemoryStore(), object(), {}, lambda: True, sports=scope)


@pytest.mark.parametrize("options", [{"requests": 2}, {"requests": True}, {"seconds": 1},
                                    {"max_games": 100}, {"monthly_requests": 0},
                                    {"prop_pages": 1001}, {"interval": float("nan")}])
def test_bounded_budget_configuration(options):
    with pytest.raises(ValueError):
        PaidScanLimits(**options)


def test_budget_time_and_lease_stop_before_spending():
    store = MemoryStore()
    limits = PaidScanLimits(seconds=30, interval=0)
    budget = RequestBudget(store, limits, lambda: True, clock=lambda: 0, deadline=15)
    with pytest.raises(BallDontLieError, match="TIME_BUDGET_EXHAUSTED"):
        budget.reserve("NBA", "provider")
    assert store.charges == []
    budget = RequestBudget(store, limits, lambda: False, clock=lambda: 0)
    with pytest.raises(BallDontLieError, match="SCANNER_LEASE_LOST"):
        budget.reserve("NBA", "provider")
    assert store.charges == []


def test_shared_budget_paces_sports_and_lab_requests():
    clock = [0.0]
    store = MemoryStore()
    budget = RequestBudget(store, PaidScanLimits(seconds=60, interval=13), lambda: True,
                           clock=lambda: clock[0], sleep=lambda n: clock.__setitem__(0, clock[0] + n))
    budget.reserve("NBA", "sports")
    budget.reserve("NFL", "sports")
    budget.reserve("NBA", "lab")
    assert clock[0] == 26 and budget.used == 3
    assert budget.by_sport == {"NBA": 2, "NFL": 1}


def test_paginator_cycle_is_partial_and_duplicate_game_calls_are_cached():
    class Cycle:
        def fetch(self, sport, resource, params):
            return {"data": [game("NBA")] if resource == "games" else [quote("NBA")],
                    "meta": {} if resource == "games" else {"next_cursor": "same"}}
    store = MemoryStore()
    budget = RequestBudget(store, PaidScanLimits(seconds=60, interval=0), lambda: True)
    pages = BoundedPages(Cycle(), budget, "NBA", 10)
    assert pages.fetch_all_pages("nba", "games")["complete"]
    assert pages.fetch_all_pages("nba", "games")["complete"]
    assert budget.used == 1
    result = pages.fetch_all_pages("nba", "props")
    assert result["complete"] is False and result["pages"] == 2
    assert result["reason"] == "INVALID_PAGINATION_CURSOR"
    with pytest.raises(BallDontLieError, match="SPORT_ISOLATION"):
        pages.fetch_all_pages("nfl", "props")


def test_central_calendar_includes_late_game_not_tomorrows_slate():
    # November 1 is CST: 05:00 UTC November 2 still belongs to November 1.
    late = game("NBA", datetime(2026, 11, 2, 5, tzinfo=UTC))
    tomorrow = game("NBA", datetime(2026, 11, 2, 20, tzinfo=UTC), id=88)
    started = game("NBA", NOW - timedelta(minutes=1), id=89)
    report, _, provider = run(sports=("NBA",), provider=PaidProvider(games=[late, tomorrow, started]), mappings=False)
    assert report["sports"]["NBA"]["eligible_games"] == 1
    assert [dict(p)["game_id"] for _, resource, p in provider.calls if resource == "props"] == [77]
    dates = [v for k, v in provider.calls[0][2] if k == "dates[]"]
    assert dates == ["2026-11-01", "2026-11-02"]


def test_latest_pregame_feature_wins_but_equal_time_conflicts_stay_ambiguous():
    store = MemoryStore()
    models = seed(store, ("NBA",))
    _, snap, _ = evidence("NBA")
    older = {**snap, "features_available_at": (NOW - timedelta(minutes=5)).isoformat()}
    store.append("player_feature_snapshot", "NBA", older, "older")
    _, snapshots, _ = stored_evidence(store, "NBA", models, NOW)
    assert snapshots == [snap]
    conflict = {**snap, "source_checksum": "d" * 64}
    store.append("player_feature_snapshot", "NBA", conflict, "conflict")
    _, snapshots, _ = stored_evidence(store, "NBA", models, NOW)
    assert len(snapshots) == 2


def test_read_filters_expired_prices_and_next_day_without_mutating_evidence():
    report, store, _ = run()
    original = deepcopy(report)
    current = present_paid_scan(report, now=NOW, include_rows=True)
    assert current["sports"]["NBA"]["current_model_rows"] == 2
    assert vip_research_rows(current, "NBA")[0]["executable_sportsbook_ticket_verified"] is False
    late = present_paid_scan(report, now=NOW + timedelta(seconds=121), include_rows=True)
    assert all(not r["research_rows"] for r in late["sports"].values())
    assert read_saved_paid_scan(store, now=NOW + timedelta(days=1))["reason"] == "NO_MATCHING_PAID_SNAPSHOT"
    assert report == original
    assert len(store.charges) == 6  # Reads never call a paid provider.


def test_scan_top10_per_category_is_not_cut_off_by_overall_top10():
    rows = []
    for market in ("player_points", "player_rebounds", "player_assists"):
        for i in range(12):
            rows.append({"sport": "basketball_nba", "event_id": "game",
                         "participant": f"Fixture {i}", "market": market,
                         "model_probability": .8 - i * .01, "model_version": "fixture",
                         "probability_status": "VALIDATING", "price_is_current": True,
                         "selection": "over", "line": 10.5})
    report = from_scan_actions(rows, present=lambda row: row)
    nba = report["sports"]["NBA"]
    assert len(nba["top10"]) == 10
    assert {k: len(v) for k, v in nba["top10_by_market"].items()} == {
        "player_points": 10, "player_rebounds": 10, "player_assists": 10}
    assert all(r["approved_for_betting"] is False for v in nba["top10_by_market"].values() for r in v)

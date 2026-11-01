"""V7 paid-player research stage for the EXISTING scanner.

Collects NBA/NFL/NHL independently of the small rotating Odds API prop sample.
Uses existing paid adapters, reviewed identity manifests, frozen feature records
and loaded fitted models. Never creates a model, purchases access, approves a
wager, or publishes to Discord. All provider and LAB signals remain distinct.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import os
import time
import uuid
from zoneinfo import ZoneInfo

from .boost_goat_inference_acceptance import audit_exact_line_research
from .boost_market_coverage import summarize_prop_markets
from .boost_market_manifest import audit_priority_market_presence
from .boost_scope import BoostScope, SPORTS
from .boost_slate import inspect_sport_slate
from .paid_player_evidence import (
    feature_inventory, matching_game_crosswalks, refresh_reviewed_features, freeze_two_sided_forecasts,
)
from .persistence.store import digest
from .providers.balldontlie import BallDontLieError, BallDontLieProvider
from .vip.paid_models import LabUnavailable, read_paid_player_models

CENTRAL = ZoneInfo("America/Chicago")
MAX_ROWS = 10000


@dataclass(frozen=True)
class PaidScanLimits:
    requests: int = 90
    seconds: int = 180
    monthly_requests: int = 12000
    max_games: int = 25
    prop_pages: int = 25
    interval: float = 13.0

    def __post_init__(self):
        for value, low, high in ((self.requests, 3, 1000), (self.seconds, 30, 480),
                                 (self.monthly_requests, 1, 1000000),
                                 (self.max_games, 1, 25), (self.prop_pages, 1, 100)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid bounded paid scan configuration")
        # Lower than the existing conservative pacing requires a reviewed account
        # rate limit; configuration alone does not establish that entitlement.
        if not isinstance(self.interval, (int, float)) or not 0 <= self.interval <= 60:
            raise ValueError("Invalid paid provider pacing")

    @classmethod
    def from_environment(cls):
        interval = float(os.getenv("JABBAZI_PAID_SCAN_INTERVAL_SECONDS", "13"))
        if interval < 13:
            # Do not infer a faster account tier merely from a configured key.
            # This is operator-supplied entitlement evidence, not an upgrade.
            verified = os.getenv("JABBAZI_PAID_SCAN_RATE_LIMIT_VERIFIED", "false").lower() == "true"
            rpm = int(os.getenv("JABBAZI_PAID_SCAN_VERIFIED_REQUESTS_PER_MINUTE", "0"))
            if not verified or not 1 <= rpm <= 600 or interval < 60 / rpm:
                raise ValueError("Faster paid pacing requires a verified shared provider limit")
        return cls(
            requests=int(os.getenv("JABBAZI_PAID_SCAN_REQUESTS", "90")),
            seconds=int(os.getenv("JABBAZI_PAID_SCAN_SECONDS", "180")),
            monthly_requests=int(os.getenv("JABBAZI_PAID_SCAN_MONTHLY_REQUESTS", "12000")),
            max_games=int(os.getenv("JABBAZI_PAID_SCAN_MAX_GAMES", "25")),
            prop_pages=int(os.getenv("JABBAZI_PAID_SCAN_MAX_PROP_PAGES", "25")),
            interval=interval,
        )


class RequestBudget:
    """One durable local request allowance; NOT a provider account balance."""
    def __init__(self, store, limits, renew, *, deadline=None, clock=time.monotonic,
                 sleep=time.sleep, run_id=None, progress=None):
        self.store, self.limits, self.renew = store, limits, renew
        self.clock, self.sleep, self.progress = clock, sleep, progress
        self.deadline = min(clock() + limits.seconds, deadline) if deadline is not None else clock() + limits.seconds
        self.run_id = run_id or str(uuid.uuid4())
        self.used = 0
        self.last = None
        self.by_sport = Counter()
        self.stopped = None

    def reserve(self, sport, provider):
        if self.stopped:
            raise BallDontLieError(self.stopped)
        if self.used >= self.limits.requests:
            self.stopped = "REQUEST_BUDGET_EXHAUSTED"
            raise BallDontLieError(self.stopped)
        delay = max(0, self.limits.interval - (self.clock() - self.last)) if self.last is not None else 0
        # Leave room for the adapter's bounded socket timeout before starting.
        if self.clock() + delay + 16 >= self.deadline:
            self.stopped = "TIME_BUDGET_EXHAUSTED"
            raise BallDontLieError(self.stopped)
        if not self.renew():
            self.stopped = "SCANNER_LEASE_LOST"
            raise BallDontLieError(self.stopped)
        if delay:
            self.sleep(delay)
        if not self.store.claim_credits(
            provider, 1, monthly_limit=self.limits.monthly_requests,
            key=f"{self.run_id}:{provider}:{self.used}",
        ):
            self.stopped = "MONTHLY_REQUEST_LIMIT"
            raise BallDontLieError(self.stopped)
        self.used += 1
        self.by_sport[sport] += 1
        self.last = self.clock()
        if self.progress is not None:
            self.progress("PAID_PLAYER_COLLECTION", SPORTS[sport], paid_requests=self.used)


class BoundedPages:
    """Reuses the existing HTTP adapter; preserves usable partial prop pages.

    The caller must honor complete=False. Partial game discovery is not used
    to assert an independently complete league slate. No implicit retries.
    """
    def __init__(self, provider, budget, sport, allowance):
        self.provider, self.budget, self.sport = provider, budget, sport
        self.allowance, self.used, self.rows_seen = allowance, 0, 0
        self.stop_reason = None
        self.cache = {}

    def fetch_all_pages(self, sport, resource, params=None, *, max_pages=100):
        if sport != self.sport.lower():
            raise BallDontLieError("SPORT_ISOLATION_VIOLATION")
        params = list(params or [])
        if not 1 <= max_pages <= 1000 or any(k == "cursor" for k, _ in params):
            raise ValueError("Invalid managed pagination")
        cache_key = (sport, resource, tuple(params))
        if cache_key in self.cache:
            return deepcopy(self.cache[cache_key])
        rows, cursors, pages = [], set(), 0
        while pages < max_pages:
            try:
                if self.used >= self.allowance:
                    raise BallDontLieError("SPORT_REQUEST_BUDGET_EXHAUSTED")
                self.budget.reserve(self.sport, "balldontlie_sports")
                self.used += 1
                response = self.provider.fetch(sport, resource, params)
            except BallDontLieError as exc:
                self.stop_reason = str(exc)
                if str(exc) == "HTTP_429":
                    self.budget.stopped = "HTTP_429"
                if not pages:
                    raise
                return {"data": rows, "pages": pages, "complete": False, "reason": str(exc)}
            pages += 1
            remaining = MAX_ROWS - self.rows_seen
            received = response["data"]
            accepted = received[:max(0, remaining)]
            rows.extend(accepted)
            self.rows_seen += len(accepted)
            if len(received) > remaining:
                self.stop_reason = "ROW_LIMIT_REACHED"
                return {"data": rows, "pages": pages, "complete": False, "reason": self.stop_reason}
            cursor = response.get("meta", {}).get("next_cursor")
            if cursor is None:
                result = {"data": rows, "pages": pages, "complete": True}
                if resource == "games":
                    self.cache[cache_key] = deepcopy(result)
                return result
            if isinstance(cursor, bool) or not isinstance(cursor, (str, int)) or not str(cursor) or str(cursor) in cursors:
                self.stop_reason = "INVALID_PAGINATION_CURSOR"
                return {"data": rows, "pages": pages, "complete": False, "reason": self.stop_reason}
            cursors.add(str(cursor))
            params = [(k, v) for k, v in params if k != "cursor"] + [("cursor", cursor)]
        self.stop_reason = "PAGINATION_LIMIT_REACHED"
        return {"data": rows, "pages": pages, "complete": False, "reason": self.stop_reason}


def _stamp(value):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.astimezone(UTC) if value.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def stored_evidence(store, sport, player_models, now):
    """Select the latest pregame features; equal-time conflicts stay ambiguous."""
    manifests = store.list_records("paid_player_identity_manifest", 1, entity=sport)
    crosswalks = manifests[0]["payload"].get("records", []) if manifests else []
    if not isinstance(crosswalks, list) or len(crosswalks) > MAX_ROWS:
        raise ValueError("Invalid private reviewed manifest")
    records = feature_inventory(store, sport, crosswalks, limit=MAX_ROWS + 1)
    if len(records) > MAX_ROWS:
        raise ValueError("Feature inventory cap reached; scope inventory before acceptance")
    latest = {}
    for record in records:
        row = record.get("payload", {})
        if row.get("sport") != SPORTS[sport]:
            continue
        at, start = _stamp(row.get("features_available_at")), _stamp(row.get("starts_at"))
        if at is None or start is None or not now - timedelta(hours=1) <= at <= now < start:
            continue
        key = (row.get("event_id"), str(row.get("player_id")), row.get("market"))
        if key not in latest or at > latest[key][0]:
            latest[key] = (at, [row])
        elif at == latest[key][0] and row not in latest[key][1]:
            latest[key][1].append(row)
    snapshots = [row for _, rows in latest.values() for row in rows]
    artifacts = [model.artifact for (code, _), model in player_models.items() if code == SPORTS[sport]]
    return crosswalks, snapshots, artifacts


def run_paid_player_scan(store, settings, player_models, renew, *, deadline=None,
                         limits=None, now=None, sports=("NBA", "NFL", "NHL"),
                         provider_factory=BallDontLieProvider,
                         lab_reader=read_paid_player_models, progress=None, feature_collector=None,
                         slate_date=None, boost_scope=None):
    """Actual paid collection + exact-line fitted research, never betting approval.

    Normal full scans request all three sports. An explicitly scoped boost caller
    can pass one sport; no unrelated sport is queried. The shared pipeline is not
    a claim that boost selection or NBA/NHL joint calibration has passed.
    """
    if not sports or len(sports) != len(set(sports)) or any(s not in SPORTS for s in sports):
        raise ValueError("Explicit supported sport scope required")
    limits = limits or PaidScanLimits.from_environment()
    current = (lambda: now) if now is not None else (lambda: datetime.now(UTC))
    started = current()
    if started.utcoffset() is None:
        raise ValueError("Aware scan observation required")
    today = started.astimezone(CENTRAL).date()
    day = slate_date or today
    if type(day) is not date or day not in {today, today + timedelta(days=1)}:
        raise ValueError("Only the current or next Central slate may be collected")
    if boost_scope is not None and (len(sports) != 1 or boost_scope.sport != SPORTS[sports[0]]):
        raise ValueError("A boost scope must match exactly one requested sport")
    report = {"requested": True, "scope": list(sports), "slate_date": day.isoformat(),
              "timezone": "America/Chicago", "observed_at": started.isoformat(),
              "mode": "RESEARCH_ONLY", "betting_enabled": False,
              "scope_complete": False, "paid_requests_made": 0, "sports": {},
              "provider_odds_are_hit_probabilities": False,
              "joint_calibration_validated": False, "full_market_entitlement_verified": False}
    if store is None:
        return {**report, "status": "UNAVAILABLE", "reason": "DURABLE_STORAGE_REQUIRED"}
    if os.getenv("JABBAZI_PAID_PLAYER_SCAN_ENABLED", "true").lower() != "true":
        return {**report, "requested": False, "status": "DISABLED", "reason": "OPERATOR_DISABLED"}
    budget = RequestBudget(store, limits, renew, deadline=deadline, progress=progress)
    key = getattr(settings, "balldontlie_api_key", "")
    provider = provider_factory(key, budget=limits.requests, interval=0) if key else None
    try:
        for sport in sports:
            if progress is not None:
                progress("PAID_PLAYER_COLLECTION", SPORTS[sport])
            result = {"sport": sport, "coverage": "UNAVAILABLE", "errors": [],
                      "eligible_games": 0, "accepted_quotes": 0, "research_rows": [],
                      "raw_quotes_received": 0, "pages": 0, "rejections": {},
                      "model_probability_rows": 0, "all_eligible_games_have_quotes": False,
                      "model_estimates_complete": False, "full_market_coverage_verified": False}
            report["sports"][sport] = result
            if provider is None:
                result["errors"].append("SPORTS_API_KEY_NOT_CONFIGURED")
                continue
            # Preserve a fair allowance for later sports rather than allowing the
            # first basketball slate to consume every request in the scan.
            allowance = max(1, limits.requests // len(sports))
            bounded = BoundedPages(provider, budget, sport, allowance)
            try:
                slate = inspect_sport_slate(
                    bounded, boost_scope or BoostScope(SPORTS[sport]), target_date=day,
                    max_games=limits.max_games, max_game_pages=10,
                    max_prop_pages=limits.prop_pages, observed_at=current(),
                    require_future_kickoff=True, calendar_timezone="America/Chicago",
                    retain_partial_quotes=True, quote_observed_at=now,
                )
                odds = slate.odds_report
                offers = list(odds.rows) if odds else []
                result.update(coverage=slate.coverage, eligible_games=slate.games_eligible,
                              accepted_quotes=len(offers), errors=list(slate.errors),
                              raw_quotes_received=odds.raw_odds_rows if odds else 0,
                              pages=slate.game_pages + (odds.pages if odds else 0),
                              requested_games=odds.games_requested if odds else 0,
                              responded_games=odds.games_succeeded if odds else 0)
                if bounded.stop_reason:
                    result["errors"].append(bounded.stop_reason)
                result["all_eligible_games_have_quotes"] = bool(odds and slate.games_eligible and
                    odds.games_succeeded == slate.games_eligible and
                    len(odds.game_row_counts) == slate.games_eligible and
                    all(n > 0 for _, n in odds.game_row_counts))
                if result["coverage"] == "FULL" and not result["all_eligible_games_have_quotes"]:
                    result["coverage"] = "PARTIAL"
                    result["errors"].append("EMPTY_ELIGIBLE_GAME_PROPS")
                breadth = summarize_prop_markets(offers)
                result["market_breadth"] = breadth
                result["priority_market_observations"] = audit_priority_market_presence(sport, breadth, eligible_games=slate.games_eligible)
                if offers:
                    # Private immutable licensed evidence; not sent as raw data
                    # to the chat, VIP summaries, or Discord publisher.
                    payload = {"sport": sport, "slate_date": day.isoformat(),
                               "observed_at": current().isoformat(), "rows": offers,
                               "coverage": result["coverage"]}
                    store.append("paid_player_quote_snapshot", sport, payload, digest([budget.run_id, sport, "quotes"]))
                    crosswalks, snapshots, artifacts = stored_evidence(store, sport, player_models, current())
                    crosswalks, rejected_maps = matching_game_crosswalks(sport, crosswalks, slate.game_records)
                    if rejected_maps:
                        result["errors"].append("REVIEWED_GAME_MAPPING_STALE_OR_OUT_OF_SCOPE")
                    result["feature_collection"] = refresh_reviewed_features(
                        store, sport, offers, crosswalks, snapshots, feature_collector,
                        now=current(), deadline=budget.deadline, clock=budget.clock, renew=renew,
                    )
                    if result["feature_collection"]["archived_snapshots"]:
                        _, snapshots, artifacts = stored_evidence(store, sport, player_models, current())
                    inference = audit_exact_line_research(sport, offers, crosswalks, snapshots, artifacts,
                                                         observed_at=current(), include_research_rows=True,
                                                         continue_check=lambda: budget.clock() < budget.deadline and renew())
                    rows = inference.pop("research_rows")
                    games = {g["id"]: g for g in slate.game_records}
                    for row in rows:
                        game = games.get(row["provider_game_id"], {})
                        away, home = game.get("visitor_team", game.get("away_team", {})), game.get("home_team", {})
                        row["event"] = f'{away.get("full_name", "Away")} @ {home.get("full_name", "Home")}'
                    result["prospective_capture"] = freeze_two_sided_forecasts(
                        store, rows, offers, snapshots, now=current(),
                    )
                    result.update(inference=inference, research_rows=rows,
                                  model_probability_rows=len(rows), rejections=inference["rejections"])
                    result["model_estimates_complete"] = bool(offers and inference["exact_line_research_estimates"] == len(offers))
            except (BallDontLieError, ValueError, TypeError, KeyError, ArithmeticError):
                result["coverage"] = "PARTIAL" if result["accepted_quotes"] else "FAILED"
                result["errors"].append("PAID_RESEARCH_INPUT_OR_COLLECTION_ERROR")
            result["requests_made"] = budget.by_sport[sport]
    finally:
        if provider is not None:
            provider.close()
    # Saved LAB forecasts are separate source signals. No generation/backtest
    # job is triggered; NHL unsupported player models remain explicit.
    lab_key = getattr(settings, "balldontlie_lab_api_key", "")
    for sport in sports:
        def lab_guard(sport=sport):
            try:
                budget.reserve(sport, "balldontlie_lab")
            except BallDontLieError as exc:
                raise LabUnavailable(str(exc)) from None
        try:
            lab = lab_reader(lab_key, sport, day, request_guard=lab_guard)
        except (LabUnavailable, ValueError, TypeError, KeyError, OSError):
            # Do not erase successful independent sports on one LAB failure.
            lab = {"state": "UNAVAILABLE", "reason": "LAB_COLLECTION_FAILED",
                   "coverage_complete": False, "rows": [], "betting_enabled": False}
        report["sports"][sport]["lab"] = {k: v for k, v in lab.items() if k != "rows"}
        if lab.get("rows"):
            store.append("paid_lab_signal_snapshot", sport, lab, digest([budget.run_id, sport, "lab"]))
    report["paid_requests_made"] = budget.used
    report["stop_reason"] = budget.stopped
    report["observed_at"] = current().isoformat()
    report["odds_scope_complete"] = all(r["coverage"] in {"FULL", "NO_ELIGIBLE_GAMES"} for r in report["sports"].values())
    report["lab_scope_complete"] = all(
        (sport == "NHL" or not lab_key or row["lab"].get("coverage_complete") is True)
        for sport, row in report["sports"].items()
    )
    report["model_scope_complete"] = all(
        row["model_estimates_complete"] or row["coverage"] == "NO_ELIGIBLE_GAMES"
        for row in report["sports"].values()
    )
    report["collection_complete"] = report["odds_scope_complete"] and report["lab_scope_complete"]
    report["scope_complete"] = report["collection_complete"] and report["model_scope_complete"]
    report["status"] = "RESEARCH_SCOPE_COMPLETE" if report["scope_complete"] else "PARTIAL"
    report["coverage_scope"] = "OBSERVED_ELIGIBLE_SLATE_AND_RETURNED_PROP_ROWS_WITHIN_DECLARED_LIMITS"
    report["limits"] = {"requests": limits.requests, "seconds": limits.seconds,
                        "monthly_local_requests_per_provider": limits.monthly_requests,
                        "games_per_sport": limits.max_games, "prop_pages_per_game": limits.prop_pages}
    report["notice"] = (
        "Collection and model-inference completeness are separate. This report does not "
        "certify every offered player/market, provider entitlement, sportsbook execution, "
        "prospective calibration or betting approval. Missing model rows are not zero probabilities."
    )
    # Full collection is deliberately separate from complete model estimates,
    # prospective calibration, quote execution, and full product acceptance.
    store.append("paid_player_scan", day.isoformat(), report, digest([budget.run_id, "paid_player_scan"]))
    return report


def present_paid_scan(report, *, now=None, slate_date=None, include_rows=False):
    """Recheck source times on every read; never display stale % as current."""
    now = now or datetime.now(UTC)
    day = slate_date or now.astimezone(CENTRAL).date()
    if not isinstance(report, dict) or report.get("slate_date") != day.isoformat():
        return {"status": "UNAVAILABLE", "reason": "NO_MATCHING_PAID_SNAPSHOT", "sports": {}, "betting_enabled": False}
    result = deepcopy(report)
    for sport, data in result.get("sports", {}).items():
        rows, markets = [], {}
        for row in data.pop("research_rows", []):
            source, start, model_at = _stamp(row.get("source_timestamp")), _stamp(row.get("starts_at")), _stamp(row.get("model_time"))
            if (source is None or start is None or model_at is None or
                    not 0 <= (now - source).total_seconds() <= 120 or
                    not 0 <= (now - model_at).total_seconds() <= 3600 or
                    start <= now or start.astimezone(CENTRAL).date() != day or
                    not row.get("model_version") or not row.get("participant")):
                continue
            try:
                probability = float(row.get("model_probability"))
            except (TypeError, ValueError, OverflowError):
                continue
            if (not 0 < probability < 1 or row.get("model_stage") not in {"VALIDATING", "PRODUCTION_APPROVED"}
                    or row.get("probability_basis") != "FITTED_JABBAZI_MODEL"):
                continue
            row["model_probability"] = probability
            row["approved_for_betting"] = False
            row["price_is_current"] = True
            row["probability_status"] = row["model_stage"]
            rows.append(row)
        data["current_model_rows"] = len(rows)
        rows.sort(key=lambda r: (-r["model_probability"], r["event_id"], r["participant"], r["market"]))
        seen = set()
        for row in rows:
            key = (row["event_id"], row["participant"], row["market"])
            if key in seen:
                continue
            seen.add(key)
            markets.setdefault(row["market"], []).append(row)
        data["top10_by_market"] = {m: values[:10] for m, values in markets.items()}
        data["top10"] = [r for values in markets.values() for r in values[:10]]
        data["top10"].sort(key=lambda r: -r["model_probability"])
        data["top10"] = data["top10"][:10]
        if include_rows:
            data["research_rows"] = rows
    result["betting_enabled"] = False
    return result


def read_saved_paid_scan(store, *, now=None, slate_date=None):
    day = slate_date or (now or datetime.now(UTC)).astimezone(CENTRAL).date()
    records = store.list_records("paid_player_scan", 1, entity=day.isoformat())
    if not records:
        records = store.list_records("paid_player_scan", 1, entity="latest")
    return present_paid_scan(records[0]["payload"] if records else None,
                             now=now, slate_date=slate_date, include_rows=True)


def vip_research_rows(report, sport):
    """Adapt only current genuine research estimates to the model-only view.

    Does not enter the official picks or cash-authority paths, and never asserts
    that a provider odds row is an independently executable sportsbook ticket.
    """
    output = []
    for row in report.get("sports", {}).get(sport, {}).get("research_rows", []):
        output.append({
            **row, "sport": sport, "player": row.get("participant"),
            "model_probability": row["model_probability"],
            "price_at": row["source_timestamp"], "fresh": True,
            "data_health": "HEALTHY", "status": "WATCH", "market_probability": None,
            "approved_for_betting": False, "executable_sportsbook_ticket_verified": False,
        })
    return output

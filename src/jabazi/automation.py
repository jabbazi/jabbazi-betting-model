"""Credit-aware automatic scanner service."""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, UTC
from zoneinfo import ZoneInfo
import uuid
import os
from decimal import Decimal

from .catalog import SPORTS
from .config import Settings
from .domain.arbitrage import ArbitrageOpportunity, find_arbitrage
from .domain.recommendation import ActionCard, recommend_price
from .domain.risk import RiskPolicy
from .domain.shopping import build_price_cards
from .models.registry import load_models
from .persistence.factory import ledger as Ledger
from .persistence.store import Store, digest
from .domain.portfolio import Position
from .domain.health import assess
from .domain.models import Decision
from .providers.the_odds_api import TheOddsApiProvider

QUICK_SPORTS = ("baseball_mlb", "americanfootball_nfl", "americanfootball_ncaaf")


@dataclass(frozen=True)
class AutomaticScanResult:
    feeds_scanned: int
    quotes_archived: int
    new_actions: tuple[ActionCard, ...]
    arbitrages: tuple[ArbitrageOpportunity, ...]
    credits_remaining: int | None
    errors: tuple[str, ...]
    actions: tuple[ActionCard, ...]
    slate_events: tuple[dict, ...] = ()
    event_market_coverage: dict | None = None


class AutomaticScanner:
    def __init__(
        self,
        settings: Settings,
        database: str = "jabazi-local.db",
        credit_reserve: int = 50,
        max_credits_per_run: int = 30,
    ) -> None:
        self.settings = settings
        self.database = database
        self.credit_reserve = credit_reserve
        self.max_credits_per_run = max_credits_per_run

    def _active_supported(self) -> list[dict]:
        url = "https://api.the-odds-api.com/v4/sports/?" + urllib.parse.urlencode(
            {"apiKey": self.settings.api_key}
        )
        with urllib.request.urlopen(url, timeout=20) as response:
            active = json.load(response)
        patterns = [pattern for values in SPORTS.values() for pattern in values]
        return [
            sport
            for sport in active
            if any(
                (pattern.endswith("*") and sport["key"].startswith(pattern[:-1]))
                or sport["key"] == pattern
                for pattern in patterns
            )
        ]

    def run(self, mode: str = "quick") -> AutomaticScanResult:
        ledger = Ledger(self.database)
        owner = str(uuid.uuid4())
        try:
            if isinstance(ledger, Store) and not ledger.acquire_lease("scanner", owner, 600):
                raise RuntimeError("Another scanner holds the database lease")
            return self._run(mode, ledger, owner)
        finally:
            try:
                if isinstance(ledger, Store):
                    ledger.release_lease("scanner", owner)
            finally:
                ledger.close()

    def _run(self, mode, ledger, owner):
        if mode not in {"quick", "full"}:
            raise ValueError("mode must be quick or full")
        active = self._active_supported()
        selected = (
            [sport for sport in active if sport["key"] in QUICK_SPORTS]
            if mode == "quick"
            else active
        )
        # Full scans still prioritize the owner's primary leagues within quota.
        priority = {"americanfootball_nfl": 0, "baseball_mlb": 1, "americanfootball_ncaaf": 2}
        selected.sort(key=lambda item: (priority.get(item["key"], 3), item["key"]))
        policy = RiskPolicy(
            self.settings.bankroll,
            self.settings.unit_size,
            self.settings.daily_exposure_limit,
            minimum_edge=self.settings.minimum_edge,
        )
        all_cards = []
        new_actions = []
        errors = []
        quote_count = 0
        scanned = 0
        remaining = None
        models, model_errors = load_models(ledger if isinstance(ledger, Store) else None)
        from .models.player_registry import load_player_models
        player_models, player_model_errors = load_player_models(
            ledger if isinstance(ledger, Store) else None
        )
        errors.extend(model_errors)
        errors.extend(player_model_errors)
        from .research.prospective import validation_report
        prospective = (
            validation_report(ledger)
            if isinstance(ledger, Store)
            else {"buckets": []}
        )
        actions = []
        run_id = str(uuid.uuid4())
        slate_events = {}
        from .feed_plan import FeedPlan

        from .providers.player_features_live import LivePlayerFeatureCollector
        player_features = LivePlayerFeatureCollector(
            sportsdataio_api_key=self.settings.sportsdataio_api_key
        )

        plan = FeedPlan(
            lambda sport, markets: TheOddsApiProvider(
                sport, markets=markets, api_key=self.settings.api_key
            ),
            ledger if isinstance(ledger, Store) else None,
            self.max_credits_per_run,
            self.credit_reserve,
            errors,
            lambda: not isinstance(ledger, Store) or ledger.acquire_lease("scanner", owner, 600),
            player_models=player_models,
        )
        for sport, batch in plan.batches(selected):
            try:
                ledger.archive_batch(batch)
                scanned += 1
                quote_count += len(batch.quotes)
                remaining = batch.requests_remaining
                # Preserve every event returned by the feed, even when all of its
                # prices fail freshness/completeness checks. Never invent prices.
                raw_events = json.loads(batch.raw_payload)
                if isinstance(raw_events, dict):
                    raw_events = [raw_events]
                for event in raw_events:
                    if not isinstance(event, dict) or not event.get("id"):
                        continue
                    slate_events[(sport["key"], str(event["id"]))] = {
                        "sport": sport["key"],
                        "event_id": str(event["id"]),
                        "event": f"{event.get('away_team', '?')} @ {event.get('home_team', '?')}",
                        "starts_at_utc": event.get("commence_time", ""),
                    }
                from .reliability.integrity import duplicate_event_ids
                duplicate_ids = duplicate_event_ids(batch.quotes)
                if duplicate_ids:
                    errors.extend(f"{sport['key']}:{event}:DUPLICATE_EVENT_IDENTITY" for event in sorted(duplicate_ids))
                cards = build_price_cards(batch.quotes, policy.stale_after_seconds)
                all_cards.extend(cards)
                if isinstance(ledger, Store) and any(card.participant for card in cards):
                    player_features.sync(ledger, cards)
                for card in cards:
                    model = (
                        player_models.get((card.sport, card.market))
                        if card.participant
                        else models.get(card.sport)
                    )
                    # One bad game/model must not abort independent price research.
                    try:
                        estimate = model.estimate(card) if model and card.event_id not in duplicate_ids else None
                    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                        estimate = None
                        errors.append(f"{card.sport}:{card.event_id}:model_{type(exc).__name__}")
                    from .reliability.layer import evaluate as reliability_evaluate
                    reliability = reliability_evaluate(card, estimate, model, prospective)
                    if estimate and isinstance(ledger, Store):
                        evidence = {
                            "event_id": card.event_id,
                            "sport": card.sport,
                            "market": card.market,
                            "selection": card.selection,
                            "line": card.line,
                            "probability": estimate.probability,
                            "uncertainty": estimate.uncertainty,
                            "model_version": estimate.model_version,
                            "approved_for_betting": estimate.approved_for_betting,
                            "observed_at": card.observed_at.isoformat(),
                            "features": estimate.feature_snapshot,
                            "odds_snapshot_ids": card.quote_ids,
                            "odds_snapshot": {"book": card.best_book, "decimal": card.best_decimal,
                                              "source_timestamp": card.source_timestamp},
                            "reliability": reliability,
                        }
                        ledger.append("model_prediction", card.event_id, evidence, digest(evidence))
                        try:
                            if card.participant:
                                from .research.player_prospective import freeze_player_candidate
                                reliability["prospective_recorded"] = freeze_player_candidate(
                                    ledger, card, estimate, reliability
                                )
                            else:
                                from .research.prospective import freeze_candidate
                                reliability["prospective_recorded"] = freeze_candidate(
                                    ledger, card, estimate, reliability
                                )
                        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                            reliability["prospective_recorded"] = False
                            reliability["prospective_error"] = type(exc).__name__
                    action = recommend_price(
                        card,
                        policy,
                        model_probability=estimate.probability if estimate else None,
                        uncertainty=estimate.uncertainty if estimate else Decimal(0),
                        current_exposure=ledger.open_exposure(),
                        model_validated=bool(
                            estimate and reliability["model_can_influence_cash"]
                        ),
                        jurisdiction=self.settings.jurisdiction,
                    )
                    action = replace(
                        action,
                        model_version=estimate.model_version if estimate else None,
                        probability_edge=(estimate.probability - card.consensus_probability)
                        if estimate
                        else None,
                        expected_roi=action.estimated_ev,
                        uncertainty=estimate.uncertainty if estimate else None,
                        reliability=reliability,
                    )
                    if action.decision == Decision.BET_NOW:
                        health = assess(
                            now=datetime.now(UTC),
                            observed_at=card.observed_at,
                            source_at=card.source_timestamp,
                            starts_at=card.starts_at,
                            model_approved=bool(
                                estimate and reliability["model_can_influence_cash"]
                            ),
                            database_ok=isinstance(ledger, Store),
                            required_features=("production_inputs_verified",),
                            available_features=("production_inputs_verified",)
                            if estimate
                            and estimate.feature_snapshot.get("production_inputs_verified") is True
                            else (),
                        )
                        if not health.healthy:
                            action = replace(
                                action,
                                decision=Decision.WATCH,
                                stake=Decimal(0),
                                reason=" / ".join(health.reasons),
                            )
                        else:
                            proposal = Position(
                                Decimal(0),
                                card.sport,
                                card.event_id,
                                players=frozenset({card.participant})
                                if card.participant
                                else frozenset(),
                                theses=__import__("jabazi.domain.thesis", fromlist=["tags"]).tags(card),
                                betting_date=datetime.now(UTC)
                                .astimezone(ZoneInfo(self.settings.timezone))
                                .date()
                                .isoformat(),
                            )
                            limits = self.settings.portfolio_limits()
                            reservation_id = digest(
                                [
                                    card.event_id,
                                    card.market,
                                    card.selection,
                                    str(card.line),
                                    card.source_timestamp.isoformat(),
                                    str(card.best_decimal),
                                    estimate.model_version,
                                ]
                            )
                            amount = ledger.reserve(
                                reservation_id,
                                proposal,
                                estimate.probability * (1 - estimate.uncertainty),
                                card.best_decimal,
                                limits,
                                model_version=estimate.model_version,
                                drawdown=Decimal(os.getenv("JABBAZI_CURRENT_DRAWDOWN", "0")),
                            )
                            action = replace(
                                action,
                                stake=amount,
                                reservation_id=reservation_id if amount else None,
                                decision=Decision.BET_NOW if amount else Decision.PASS,
                                reason=action.reason
                                if amount
                                else "Central portfolio limits leave no capacity",
                            )
                    actions.append(action)
            except Exception as exc:
                errors.append(f"{sport['key']}:{type(exc).__name__}")
        arbitrages = find_arbitrage(all_cards, self.settings.unit_size)
        if errors:

            def suppress(a):
                if a.reservation_id and isinstance(ledger, Store):
                    ledger.transition(
                        a.reservation_id,
                        "cancelled",
                        actor="scanner",
                        evidence={"reason": "DATA_UNHEALTHY", "scan_id": run_id},
                        event_key=digest(["cancel", run_id, a.reservation_id]),
                    )
                return (
                    replace(
                        a,
                        decision=Decision.WATCH,
                        stake=Decimal(0),
                        reason="DATA_UNHEALTHY: scan encountered errors",
                    )
                    if a.decision == Decision.BET_NOW
                    else a
                )

            actions = [suppress(a) for a in actions]
            arbitrages = []
        # Persist only final decisions after the entire pass has cleared health checks.
        for action in actions:
            if ledger.record_action_card(action):
                new_actions.append(action)
        if isinstance(ledger, Store):
            ledger.append(
                "scan_run",
                run_id,
                {
                    "event_market_coverage": plan.coverage,
                    "feeds_scanned": scanned,
                    "quotes_archived": quote_count,
                    "errors": errors,
                    "completed_at": datetime.now(UTC).isoformat(),
                    "healthy": not errors,
                    "models_loaded": {
                        "team": {
                            sport: getattr(model, "artifact", {}).get("model_version")
                            for sport, model in models.items()
                        },
                        "player": {
                            f"{sport}|{market}": getattr(model, "artifact", {}).get("model_version")
                            for (sport, market), model in player_models.items()
                        },
                    },
                    "modeled_actions": sum(a.model_probability is not None for a in actions),
                    "unmodeled_actions": sum(a.model_probability is None for a in actions),
                },
                run_id,
            )
        if plan.coverage is not None:
            plan.coverage["player_feature_diagnostics"] = list(player_features.diagnostics)[-50:]
            plan.coverage["player_feature_provider_configured"] = bool(
                self.settings.sportsdataio_api_key
            )
        return AutomaticScanResult(
            scanned,
            quote_count,
            tuple(new_actions),
            tuple(arbitrages),
            remaining,
            tuple(errors),
            tuple(actions),
            tuple(slate_events.values()),
            plan.coverage,
        )

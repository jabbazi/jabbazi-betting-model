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
        models, model_errors = load_models()
        errors.extend(model_errors)
        actions = []
        run_id = str(uuid.uuid4())
        spent_this_run = 0
        for sport in selected:
            if isinstance(ledger, Store) and not ledger.acquire_lease("scanner", owner, 600):
                raise RuntimeError("Scanner lease could not be renewed")
            markets = ("outrights",) if sport.get("has_outrights") else ("h2h", "spreads", "totals")
            estimated_cost = 1 if markets == ("outrights",) else 3
            if spent_this_run + estimated_cost > self.max_credits_per_run:
                break
            if remaining is not None and remaining - estimated_cost < self.credit_reserve:
                break
            try:
                # Charge the local budget before requesting: failed responses can still cost quota.
                if isinstance(ledger, Store):
                    from .operations import reserve_request

                    if not reserve_request(ledger, estimated_cost):
                        errors.append("MONTHLY_QUOTA_LIMIT")
                        break
                spent_this_run += estimated_cost
                batch = TheOddsApiProvider(
                    sport["key"], markets=markets, api_key=self.settings.api_key
                ).fetch()
                ledger.archive_batch(batch)
                scanned += 1
                quote_count += len(batch.quotes)
                remaining = batch.requests_remaining
                cards = build_price_cards(batch.quotes, policy.stale_after_seconds)
                all_cards.extend(cards)
                for card in cards:
                    model = models.get(card.sport)
                    estimate = model.estimate(card) if model else None
                    action = recommend_price(
                        card,
                        policy,
                        model_probability=estimate.probability if estimate else None,
                        uncertainty=estimate.uncertainty if estimate else Decimal(0),
                        current_exposure=ledger.open_exposure(),
                        model_validated=estimate.approved_for_betting if estimate else False,
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
                    )
                    if action.decision == Decision.BET_NOW:
                        health = assess(
                            now=datetime.now(UTC),
                            observed_at=card.observed_at,
                            source_at=card.source_timestamp,
                            starts_at=card.starts_at,
                            model_approved=bool(estimate and estimate.approved_for_betting),
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
                                theses=frozenset({card.event_id + ":" + card.selection}),
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
                    "feeds_scanned": scanned,
                    "quotes_archived": quote_count,
                    "errors": errors,
                    "completed_at": datetime.now(UTC).isoformat(),
                    "healthy": not errors,
                },
                run_id,
            )
        return AutomaticScanResult(
            scanned,
            quote_count,
            tuple(new_actions),
            tuple(arbitrages),
            remaining,
            tuple(errors),
            tuple(actions),
        )

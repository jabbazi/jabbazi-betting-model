"""Replay supplied point-in-time decisions; never reconstruct unavailable prices.

This is an execution/evaluation harness. Strategy predictions must be produced
by a separate walk-forward model; the harness does not select profitable periods
or fit a strategy using the settlement columns.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from collections import defaultdict
from .evaluation import Observation, evaluate
from jabazi.domain.pricing import probability, number, decimal_price


@dataclass(frozen=True)
class HistoricalDecision:
    id: str
    sport: str
    market: str
    model_version: str
    decision_at: datetime
    starts_at: datetime
    settled_at: datetime
    features_available_at: datetime
    model_fitted_at: datetime
    odds_available_at: datetime
    odds_source_at: datetime
    probability: D
    market_probability: D
    decimal_odds: D
    stake: D
    outcome: int | None  # None means push/void; never an unresolved result.
    available_stake: D
    closing_probability: D | None = None
    closing_at: datetime | None = None

    def __post_init__(self):
        timestamps = (
            self.decision_at,
            self.starts_at,
            self.settled_at,
            self.features_available_at,
            self.model_fitted_at,
            self.odds_available_at,
            self.odds_source_at,
        )
        if any(t.tzinfo is None for t in timestamps):
            raise ValueError("Aware timestamps required")
        if not self.decision_at < self.starts_at <= self.settled_at:
            raise ValueError("Invalid prediction or settlement timing")
        if (
            max(
                self.features_available_at,
                self.model_fitted_at,
                self.odds_available_at,
                self.odds_source_at,
            )
            > self.decision_at
        ):
            raise ValueError("Future information cannot enter a historical decision")
        if self.odds_source_at > self.odds_available_at:
            raise ValueError("Invalid odds receipt time")
        probability(self.probability)
        probability(self.market_probability)
        decimal_price(self.decimal_odds)
        if number(self.stake) <= 0 or number(self.available_stake) < 0:
            raise ValueError("Invalid stake/limit")
        if self.outcome not in (0, 1, None):
            raise ValueError("Unresolved/invalid outcome")
        if not all((self.id, self.sport, self.market, self.model_version)):
            raise ValueError("Missing identity")
        if (self.closing_probability is None) != (self.closing_at is None):
            raise ValueError("Closing probability needs its timestamp")
        if self.closing_at is not None:
            probability(self.closing_probability)
            if (
                self.closing_at.tzinfo is None
                or not self.decision_at <= self.closing_at <= self.starts_at
            ):
                raise ValueError("Invalid pregame closing observation")


def replay(
    rows,
    *,
    initial_bankroll,
    unit_size,
    max_odds_age_seconds=120,
    decimal_slippage=0,
    cost_per_bet=0,
    max_closing_age_seconds=300,
):
    bankroll = number(initial_bankroll)
    unit_size = number(unit_size)
    slippage = number(decimal_slippage)
    cost = number(cost_per_bet)
    if bankroll <= 0 or unit_size <= 0 or slippage < 0 or cost < 0:
        raise ValueError("Invalid execution assumptions")
    if max_odds_age_seconds <= 0 or max_closing_age_seconds <= 0:
        raise ValueError("Freshness limits must be positive")
    if len({r.id for r in rows}) != len(rows):
        raise ValueError("Duplicate historical decision")
    rows = sorted(rows, key=lambda r: (r.decision_at, r.id))
    accepted = []
    rejected = []
    pending = []
    open_stake = D(0)
    peak = bankroll
    maximum_drawdown = D(0)

    def settle(until):
        nonlocal bankroll, open_stake, peak, maximum_drawdown, pending
        due = sorted(
            [r for r in pending if r["settled_at"] <= until],
            key=lambda r: (r["settled_at"], r["id"]),
        )
        for r in due:
            bankroll += r["profit"]
            open_stake -= r["stake"] + cost
            peak = max(peak, bankroll)
            maximum_drawdown = max(maximum_drawdown, (peak - bankroll) / peak)
        pending = [r for r in pending if r["settled_at"] > until]

    for r in rows:
        settle(r.decision_at)
        offered = r.decimal_odds - slippage
        reason = None
        if (r.decision_at - r.odds_source_at).total_seconds() > max_odds_age_seconds:
            reason = "STALE_ODDS"
        elif offered <= 1:
            reason = "UNEXECUTABLE_PRICE"
        elif r.stake > r.available_stake:
            reason = "LIMIT_UNAVAILABLE"
        elif r.stake + cost > bankroll - open_stake:
            reason = "BANKROLL_UNAVAILABLE"
        if reason:
            rejected.append({"id": r.id, "reason": reason})
            continue
        profit = (
            D(0) if r.outcome is None else r.stake * (offered - 1) if r.outcome else -r.stake
        ) - cost
        closing_ok = (
            r.closing_at is not None
            and (r.starts_at - r.closing_at).total_seconds() <= max_closing_age_seconds
        )
        evidence = {
            "id": r.id,
            "sport": r.sport,
            "market": r.market,
            "model_version": r.model_version,
            "stake": r.stake,
            "decimal_odds": offered,
            "profit": profit,
            "outcome": r.outcome,
            "probability": r.probability,
            "edge": r.probability - r.market_probability,
            "settled_at": r.settled_at,
            "decision_at": r.decision_at,
            "starts_at": r.starts_at,
            "clv": r.closing_probability - r.market_probability if closing_ok else None,
        }
        accepted.append(evidence)
        pending.append(evidence)
        open_stake += r.stake + cost
    if pending:
        settle(max(r["settled_at"] for r in pending))

    def summary(items):
        stake = sum((r["stake"] for r in items), D(0))
        profit = sum((r["profit"] for r in items), D(0))
        decisive = [r for r in items if r["outcome"] is not None]
        clv = [r["clv"] for r in items if r["clv"] is not None]
        scores = (
            evaluate(
                [
                    Observation(
                        float(r["probability"]),
                        r["outcome"],
                        r["decision_at"],
                        r["starts_at"],
                        r["settled_at"],
                        r["model_version"],
                    )
                    for r in decisive
                ]
            )
            if decisive
            else None
        )
        return {
            "n": len(items),
            "decisive_n": len(decisive),
            "stake": stake,
            "profit": profit,
            "units": profit / unit_size,
            "roi": profit / stake if stake else None,
            "win_rate": sum(r["outcome"] for r in decisive) / len(decisive) if decisive else None,
            "average_decimal_odds": sum((r["decimal_odds"] for r in items), D(0)) / len(items)
            if items
            else None,
            "clv_n": len(clv),
            "average_probability_clv": sum(clv) / len(clv) if clv else None,
            "fraction_beating_close": sum(x > 0 for x in clv) / len(clv) if clv else None,
            "probability_scores": scores,
        }

    groups = {}
    for dimension in ("sport", "market", "edge_bucket", "probability_bucket"):
        buckets = defaultdict(list)
        for r in accepted:
            if dimension == "edge_bucket":
                key = (
                    "negative"
                    if r["edge"] < 0
                    else "0–2pp"
                    if r["edge"] < D(".02")
                    else "2–5pp"
                    if r["edge"] < D(".05")
                    else "5pp+"
                )
            elif dimension == "probability_bucket":
                key = (
                    str(min(int(r["probability"] * 10), 9) * 10)
                    + "–"
                    + str(min(int(r["probability"] * 10), 9) * 10 + 10)
                    + "%"
                )
            else:
                key = r[dimension]
            buckets[key].append(r)
        groups[dimension] = {key: summary(items) for key, items in buckets.items()}
    return {
        "status": "RESEARCH_BACKTEST",
        "input_n": len(rows),
        "summary": summary(accepted),
        "rejected": rejected,
        "groups": groups,
        "max_settled_drawdown": maximum_drawdown,
        "final_bankroll": bankroll,
        "model_versions": sorted({r.model_version for r in rows}),
        "period_start": rows[0].decision_at if rows else None,
        "period_end": rows[-1].decision_at if rows else None,
        "assumptions": {
            "decimal_slippage": slippage,
            "cost_per_bet": cost,
            "unit_size": unit_size,
            "max_odds_age_seconds": max_odds_age_seconds,
            "max_closing_age_seconds": max_closing_age_seconds,
        },
    }

"""JABBAZI GURU V4.2 reliability layer.

This module is intentionally dependency-light so it can be embedded in the cloud
scanner or imported by validation jobs without changing the existing model service.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Sequence, Iterable


class ModelStage(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    SHADOW_ONLY = "SHADOW_ONLY"
    VALIDATING = "VALIDATING"
    LIMITED_LIVE = "LIMITED_LIVE"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"


class Decision(str, Enum):
    BET_NOW = "BET_NOW"
    WATCH = "WATCH"
    PASS = "PASS"


@dataclass(frozen=True)
class MarketIdentity:
    sport: str
    event_id: str
    event_date: str
    selection: str
    market_type: str
    period: str
    threshold: Optional[float] = None
    settlement_key: Optional[str] = None


@dataclass(frozen=True)
class PriceQuote:
    book: str
    american_odds: int
    observed_at: datetime
    is_current: bool


@dataclass(frozen=True)
class ModelForecast:
    model_name: str
    version: str
    stage: ModelStage
    probability: Optional[float]
    generated_at: datetime
    supported_market: bool
    uncertainty_low: Optional[float] = None
    uncertainty_high: Optional[float] = None


@dataclass(frozen=True)
class ValidationMetrics:
    sample_size: int
    brier: Optional[float] = None
    log_loss: Optional[float] = None
    calibration_slope: Optional[float] = None
    calibration_intercept: Optional[float] = None
    mean_clv_prob_points: Optional[float] = None
    roi: Optional[float] = None
    market_baseline_brier: Optional[float] = None
    frozen_prospective: bool = False
    model_version: Optional[str] = None
    market_bucket: Optional[str] = None
    stable_windows: int = 0


@dataclass(frozen=True)
class Candidate:
    identity: MarketIdentity
    quote: PriceQuote
    model: Optional[ModelForecast]
    market_no_vig_probability: Optional[float]
    external_probability: Optional[float] = None
    lineup_verified: bool = False
    event_verified: bool = False
    market_pair_verified: bool = False
    critical_news_clear: bool = False
    feature_health_ok: bool = False
    notes: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class Exposure:
    dollars: float
    sport: str
    event_id: str
    team: Optional[str] = None
    player: Optional[str] = None
    thesis_tags: Sequence[str] = field(default_factory=tuple)
    origin: str = "UNKNOWN"


def american_to_decimal(odds: int) -> float:
    if not math.isfinite(odds) or abs(odds) < 100:
        raise ValueError("Malformed American odds")
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)


def break_even_probability(odds: int) -> float:
    return 1.0 / american_to_decimal(odds)


def fair_american(probability: float) -> int:
    if not 0 < probability < 1:
        raise ValueError("probability must be between 0 and 1")
    if probability >= 0.5:
        return round(-100 * probability / (1 - probability))
    return round(100 * (1 - probability) / probability)


def expected_roi(probability: float, odds: int) -> float:
    return probability * american_to_decimal(odds) - 1.0


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("probabilities and outcomes must be same non-zero length")
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(probabilities)


def log_loss(probabilities: Sequence[float], outcomes: Sequence[int], eps: float = 1e-12) -> float:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("probabilities and outcomes must be same non-zero length")
    total = 0.0
    for p, y in zip(probabilities, outcomes):
        p = min(max(p, eps), 1 - eps)
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probabilities)


def validate_complementary_pair(probabilities: Iterable[float], tolerance: float = 0.03) -> bool:
    vals = list(probabilities)
    return (
        len(vals) == 2
        and all(math.isfinite(p) and 0 <= p <= 1 for p in vals)
        and abs(sum(vals) - 1.0) <= tolerance
    )


@dataclass(frozen=True)
class IntegrityResult:
    ok: bool
    hard_failures: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_candidate_integrity(
    candidate: Candidate, max_quote_age_minutes: int = 2, *, now=None
) -> IntegrityResult:
    hard: list[str] = []
    warn: list[str] = []
    for label, p in (
        ("MARKET_PROB", candidate.market_no_vig_probability),
        ("MODEL_PROB", candidate.model.probability if candidate.model else None),
    ):
        if p is not None and not 0.0 < p < 1.0:
            hard.append(f"{label}_OUT_OF_RANGE")
    if candidate.model:
        if not candidate.model.supported_market:
            hard.append("MODEL_MARKET_UNSUPPORTED")
        if candidate.model.probability is not None and not candidate.feature_health_ok:
            hard.append("MODEL_FEATURE_HEALTH_FAILED")
    if not candidate.event_verified:
        hard.append("EVENT_IDENTITY_UNVERIFIED")
    if not candidate.market_pair_verified:
        hard.append("MARKET_PAIRING_UNVERIFIED")
    if not candidate.lineup_verified:
        warn.append("LINEUP_OR_ROLE_UNVERIFIED")
    if not candidate.critical_news_clear:
        warn.append("CRITICAL_NEWS_UNRESOLVED")
    if not candidate.quote.is_current:
        hard.append("PRICE_NOT_CURRENT")
    seen = candidate.quote.observed_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    age = (
        (now or datetime.now(timezone.utc)) - seen.astimezone(timezone.utc)
    ).total_seconds() / 60.0
    if age < 0:
        hard.append("PRICE_FROM_FUTURE")
    if age > max_quote_age_minutes:
        hard.append("PRICE_TOO_OLD")
    if candidate.quote.american_odds == 0:
        hard.append("INVALID_AMERICAN_ODDS")
    return IntegrityResult(not hard, tuple(hard), tuple(warn))


@dataclass(frozen=True)
class PromotionPolicy:
    validating_n: int = 250
    limited_live_n: int = 750
    production_n: int = 1500
    max_brier: float = 0.245
    max_log_loss: float = 0.69
    min_calibration_slope: float = 0.80
    max_calibration_slope: float = 1.20
    max_abs_calibration_intercept: float = 0.08
    min_mean_clv_prob_points: float = 0.0
    require_market_brier_improvement: bool = True


@dataclass(frozen=True)
class PromotionResult:
    stage: ModelStage
    passed: tuple[str, ...]
    failed: tuple[str, ...]


def evaluate_promotion(
    metrics: ValidationMetrics, policy: PromotionPolicy = PromotionPolicy()
) -> PromotionResult:
    passed: list[str] = []
    failed: list[str] = []

    def gate(name: str, ok: bool) -> None:
        (passed if ok else failed).append(name)

    gate(
        "FROZEN_PROSPECTIVE",
        metrics.frozen_prospective and bool(metrics.model_version) and bool(metrics.market_bucket),
    )
    gate("STABILITY", metrics.stable_windows >= 3)
    gate("BRIER", metrics.brier is not None and metrics.brier <= policy.max_brier)
    gate("LOG_LOSS", metrics.log_loss is not None and metrics.log_loss <= policy.max_log_loss)
    gate(
        "CALIBRATION_SLOPE",
        metrics.calibration_slope is not None
        and policy.min_calibration_slope
        <= metrics.calibration_slope
        <= policy.max_calibration_slope,
    )
    gate(
        "CALIBRATION_INTERCEPT",
        metrics.calibration_intercept is not None
        and abs(metrics.calibration_intercept) <= policy.max_abs_calibration_intercept,
    )
    gate(
        "CLV",
        metrics.mean_clv_prob_points is not None
        and metrics.mean_clv_prob_points >= policy.min_mean_clv_prob_points,
    )
    if policy.require_market_brier_improvement:
        gate(
            "BEATS_MARKET_BRIER",
            metrics.brier is not None
            and metrics.market_baseline_brier is not None
            and metrics.brier < metrics.market_baseline_brier,
        )
    if not metrics.frozen_prospective or not metrics.model_version or not metrics.market_bucket:
        stage = ModelStage.SHADOW_ONLY
    elif metrics.sample_size < policy.validating_n:
        stage = ModelStage.SHADOW_ONLY
    elif metrics.sample_size < policy.limited_live_n:
        stage = ModelStage.VALIDATING
    elif metrics.sample_size < policy.production_n:
        stage = ModelStage.LIMITED_LIVE if not failed else ModelStage.VALIDATING
    else:
        stage = ModelStage.PRODUCTION_APPROVED if not failed else ModelStage.VALIDATING
    return PromotionResult(stage, tuple(passed), tuple(failed))


@dataclass(frozen=True)
class EdgeAssessment:
    model_probability: Optional[float]
    market_probability: Optional[float]
    raw_model_market_gap_pp: Optional[float]
    edge_vs_break_even_pp: Optional[float]
    expected_roi: Optional[float]
    model_can_approve: bool


def assess_edge(candidate: Candidate) -> EdgeAssessment:
    p = candidate.model.probability if candidate.model else None
    market = candidate.market_no_vig_probability
    be = break_even_probability(candidate.quote.american_odds)
    approved = bool(candidate.model and candidate.model.stage == ModelStage.PRODUCTION_APPROVED)
    return EdgeAssessment(
        p,
        market,
        None if p is None or market is None else 100 * (p - market),
        None if p is None else 100 * (p - be),
        None if p is None else expected_roi(p, candidate.quote.american_odds),
        approved,
    )


@dataclass(frozen=True)
class PriceLifecycle:
    candidate_id: str
    observed_odds: int
    recommended_odds: Optional[int] = None
    entry_odds: Optional[int] = None
    closing_odds: Optional[int] = None
    observed_at: Optional[datetime] = None
    recommended_at: Optional[datetime] = None
    entered_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    def entry_clv_probability_points(self) -> Optional[float]:
        if self.entry_odds is None or self.closing_odds is None:
            return None
        return 100 * (
            break_even_probability(self.closing_odds) - break_even_probability(self.entry_odds)
        )


@dataclass(frozen=True)
class PortfolioRisk:
    total_cash: float
    event_cash: dict[str, float]
    thesis_cash: dict[str, float]
    concentrated_events: tuple[str, ...]
    concentrated_theses: tuple[str, ...]


def assess_portfolio_risk(
    exposures: Sequence[Exposure], event_cap: float = 180.0, thesis_cap: float = 120.0
) -> PortfolioRisk:
    event_cash: dict[str, float] = defaultdict(float)
    thesis_cash: dict[str, float] = defaultdict(float)
    total = 0.0
    for e in exposures:
        if not math.isfinite(e.dollars) or e.dollars < 0:
            raise ValueError("Invalid cash exposure")
        total += e.dollars
        event_cash[e.event_id] += e.dollars
        for tag in e.thesis_tags:
            thesis_cash[tag] += e.dollars
    return PortfolioRisk(
        round(total, 2),
        dict(event_cash),
        dict(thesis_cash),
        tuple(sorted(k for k, v in event_cash.items() if v > event_cap)),
        tuple(sorted(k for k, v in thesis_cash.items() if v > thesis_cap)),
    )


@dataclass(frozen=True)
class CandidateEvaluation:
    decision: Decision
    integrity: IntegrityResult
    edge: EdgeAssessment
    reasons: tuple[str, ...]


def evaluate_model_lane(candidate: Candidate, min_edge_pp: float = 2.0) -> CandidateEvaluation:
    """Evaluate only the model lane.

    Important: V4.1 independent-research approval remains separate. SHADOW_ONLY
    returning WATCH here does not globally block an independently verified bet.
    """
    integrity = validate_candidate_integrity(candidate)
    edge = assess_edge(candidate)
    reasons: list[str] = []
    if not integrity.ok:
        reasons.extend(integrity.hard_failures)
        return CandidateEvaluation(Decision.PASS, integrity, edge, tuple(reasons))
    if integrity.warnings:
        reasons.extend(integrity.warnings)
        return CandidateEvaluation(Decision.WATCH, integrity, edge, tuple(reasons))
    if candidate.model is None or candidate.model.probability is None:
        return CandidateEvaluation(Decision.WATCH, integrity, edge, ("NO_MODEL_PROBABILITY",))
    if candidate.model.stage != ModelStage.PRODUCTION_APPROVED:
        reasons.extend(
            (f"MODEL_STAGE_{candidate.model.stage.value}", "MODEL_CANNOT_SOLELY_APPROVE_BET")
        )
        return CandidateEvaluation(Decision.WATCH, integrity, edge, tuple(reasons))
    if edge.edge_vs_break_even_pp is None or edge.edge_vs_break_even_pp < min_edge_pp:
        return CandidateEvaluation(Decision.PASS, integrity, edge, ("INSUFFICIENT_PRICE_EDGE",))
    return CandidateEvaluation(Decision.BET_NOW, integrity, edge, ("ALL_MODEL_LANE_GATES_PASSED",))

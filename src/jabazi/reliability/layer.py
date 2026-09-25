"""Market-specific model admission, anomaly burden and honest scanner fields."""

from dataclasses import dataclass
from math import isfinite
from .v42 import ModelStage


@dataclass(frozen=True)
class AnomalyPolicy:
    large_gap: float = 0.08
    extreme_gap: float = 0.20
    drift_z: float = 6.0

    def __post_init__(self):
        if not 0 < self.large_gap < self.extreme_gap < 1 or self.drift_z <= 0:
            raise ValueError("Invalid anomaly policy")


def anomaly(probability, market, checks, policy=AnomalyPolicy()):
    if not all(isfinite(p) and 0 <= p <= 1 for p in (probability, market)):
        return {"state": "QUARANTINED", "reasons": ["INVALID_PROBABILITY"], "eligible": False}
    gap = abs(probability - market)
    state = (
        "EXTREME_DISAGREEMENT"
        if gap >= policy.extreme_gap
        else "LARGE_DISAGREEMENT"
        if gap >= policy.large_gap
        else "NORMAL"
    )
    base = (
        "event_identity",
        "line_identity",
        "fresh_features",
        "schema",
        "variance",
        "pairing",
        "no_duplicate_event",
    )
    extra = ("starter", "injuries", "roster", "calibration") if state != "NORMAL" else ()
    reasons = ["UNVERIFIED_" + k.upper() for k in base + extra if checks.get(k) is not True]
    if checks.get("feature_drift"):
        reasons.append("FEATURE_DISTRIBUTION_DRIFT")
    return {
        "state": state if not reasons or state != "NORMAL" else "QUARANTINED",
        "reasons": reasons,
        "eligible": not reasons,
        "gap": probability - market,
    }


def market_bucket(market):
    return {
        "h2h": "moneyline",
        "spreads": "spread",
        "alternate_spreads": "alternate_spread",
        "totals": "total",
        "alternate_totals": "alternate_total",
        "team_totals": "team_total",
        "alternate_team_totals": "alternate_team_total",
    }.get(
        market,
        f"prop:{market}" if market.startswith(("player_", "pitcher_", "batter_")) else "unsupported",
    )


def _ece_from_table(rows):
    total = sum(int(row.get("n", 0)) for row in rows or [])
    if not total:
        return None
    return sum(
        int(row.get("n", 0))
        / total
        * abs(float(row.get("mean_probability", 0)) - float(row.get("observed_hit_rate", 0)))
        for row in rows
    )


def prospective_stage(record):
    """Conservative team-market promotion from frozen prospective evidence only."""
    model = record.get("model", {})
    market = record.get("market", {})
    n = int(model.get("n", 0) or 0)
    ece = _ece_from_table(record.get("calibration"))
    clean = (
        int(record.get("identity_failures", 0) or 0) == 0
        and int(record.get("input_verified", 0) or 0) == n
    )
    improves = (
        model.get("brier") is not None
        and market.get("brier") is not None
        and model.get("log_loss") is not None
        and market.get("log_loss") is not None
        and float(model["brier"]) + 0.002 < float(market["brier"])
        and float(model["log_loss"]) < float(market["log_loss"])
    )
    if n >= 1000 and clean and improves and ece is not None and ece <= 0.035:
        return "PRODUCTION_APPROVED", True, "Strict frozen prospective gates passed"
    if n >= 500 and clean and improves and ece is not None and ece <= 0.05:
        return "LIMITED_LIVE", False, "Prospective evidence promising; full production sample not reached"
    if n >= 100:
        return "VALIDATING", False, "Prospective sample accumulating"
    return "SHADOW_ONLY", False, "Insufficient frozen prospective promotion evidence"


def status_buckets(model, prospective=None):
    counts = {
        r["bucket"]: r
        for r in (prospective or {}).get("buckets", [])
        if r["sport"] == model.sport and r["model_version"] == model.artifact["model_version"]
    }
    result = {}
    for market in sorted(model.supported_markets):
        bucket = market_bucket(market)
        record = counts.get(bucket, {})
        stage, approved, reason = prospective_stage(record)
        result[bucket] = {
            "stage": stage,
            "model_version": model.artifact["model_version"],
            "prospective_sample_count": record.get("model", {}).get("n", 0),
            "frozen_prediction_count": record.get("frozen", 0),
            "pending_result_count": record.get("pending", 0),
            "approved_for_betting": approved,
            "calibration_ece": _ece_from_table(record.get("calibration")),
            "reason": reason,
        }
    return result


def evaluate(card, estimate, model=None, prospective=None, policy=AnomalyPolicy()):
    p = float(estimate.probability) if estimate else None
    market = float(card.consensus_probability)
    snapshot = estimate.feature_snapshot if estimate else {}
    health = snapshot.get("integrity", {})
    checks = {
        **health,
        "pairing": bool(card.book_no_vig),
        "line_identity": card.market == "h2h" or card.line is not None,
    }
    audit = (
        anomaly(p, market, checks, policy)
        if p is not None
        else {"state": "NORMAL", "reasons": [], "eligible": False}
    )
    fresh = not card.stale and not card.in_play
    if p is None:
        stage = "UNAVAILABLE"
    elif model is not None and hasattr(model, "stage"):
        stage = getattr(model, "stage")
    elif model is not None:
        stage = status_buckets(model, prospective).get(
            market_bucket(card.market), {}
        ).get("stage", "SHADOW_ONLY")
    else:
        stage = "SHADOW_ONLY"
    # Player artifacts carry their own promotion flag. Team score models are
    # promoted dynamically from the frozen prospective bucket, so a production
    # team stage may authorize influence even though the immutable score artifact
    # itself was originally trained as research-only.
    artifact_permission = bool(
        estimate
        and (
            estimate.approved_for_betting
            or (
                model is not None
                and not hasattr(model, "stage")
                and stage == "PRODUCTION_APPROVED"
            )
        )
    )
    model_can_influence = bool(
        artifact_permission
        and stage == "PRODUCTION_APPROVED"
        and audit["eligible"]
    )
    decision = (
        "MODEL_QUARANTINE"
        if p is not None and not audit["eligible"]
        else "BET_NOW"
        if model_can_influence
        else "WATCH_FOR_PRICE"
        if p is None and card.market_relative_ev > 0
        else "WATCH"
    )
    if not fresh:
        decision = "PASS"
    # Rank research work, never represent this as a chance of winning or approval.
    from .v42 import Candidate, MarketIdentity, PriceQuote, ModelForecast, evaluate_model_lane
    from jabazi.domain.odds import decimal_to_american

    legacy = evaluate_model_lane(
        Candidate(
            identity=MarketIdentity(
                card.sport,
                card.event_id,
                card.starts_at.isoformat() if card.starts_at else "",
                card.selection,
                card.market,
                "full_game",
                float(card.line) if card.line is not None else None,
            ),
            quote=PriceQuote(
                card.best_book,
                int(decimal_to_american(card.best_decimal)),
                card.source_timestamp,
                fresh,
            ),
            model=ModelForecast(
                estimate.model_name,
                estimate.model_version,
                ModelStage(stage) if stage in {member.value for member in ModelStage} else ModelStage.SHADOW_ONLY,
                p,
                card.observed_at,
                True,
            )
            if estimate
            else None,
            market_no_vig_probability=market,
            event_verified=bool(health.get("event_identity")),
            market_pair_verified=bool(card.book_no_vig),
            feature_health_ok=bool(audit["eligible"]),
            lineup_verified=bool(health.get("starter")),
            critical_news_clear=bool(health.get("injuries")),
        )
    )
    components = {
        "absolute_model_market_gap": abs(p - market) if p is not None else 0,
        "price_freshness": int(fresh),
        "data_health": int(audit["eligible"]),
        "validated_edge": None,
        "calibration_quality": None,
        "portfolio_overlap": None,
    }
    priority = round(100 * min(1, components["absolute_model_market_gap"]) + 5 * int(fresh), 2)
    prices = sorted(card.book_prices.values(), reverse=True)
    return dict(
        v42_decision=legacy.decision.value,
        v42_reasons=list(legacy.reasons),
        raw_model_probability=p,
        calibrated_model_probability=None,
        market_no_vig_probability=market,
        market_aware_probability=None,
        probability_difference=p - market if p is not None else None,
        model_market_gap=p - market if p is not None else None,
        model_stage=stage,
        market_bucket=market_bucket(card.market),
        calibration_bucket=f"{int(p * 20) * 5}-{min(100, int(p * 20) * 5 + 5)}"
        if p is not None
        else None,
        calibration_sample_size=(
            getattr(model, "artifact", {}).get("validation", {}).get("prospective_sample_count")
            or getattr(model, "artifact", {}).get("validation", {}).get("test_sample_count")
            if model is not None
            else None
        ),
        uncertainty_low=None,
        uncertainty_high=None,
        uncertainty_kind="policy_haircut_not_confidence_interval" if estimate else None,
        feature_health=health or None,
        anomaly_state=audit["state"],
        anomaly_reasons=audit["reasons"],
        model_lane_decision=decision,
        model_can_influence_cash=bool(model_can_influence and fresh),
        watch_trigger="Refresh pregame prices"
        if not fresh
        else "Validate frozen model bucket and resolve: " + ", ".join(audit["reasons"])
        if p is not None
        else "Obtain independently validated probability and fresh comparable prices",
        fair_price=None,
        play_to_price=None,
        expected_roi=None,
        break_even_probability=1 / float(card.best_decimal),
        period="full_game",
        second_best_decimal=str(prices[1]) if len(prices) > 1 else None,
        price_fragility="SINGLE_BOOK"
        if len(prices) < 2
        else "DISAGREEMENT"
        if not card.executable
        else "MULTI_BOOK",
        research_priority_score=priority,
        research_priority_components=components,
        source_provenance={
            "quote_ids": list(card.quote_ids),
            "feature_snapshot_id": snapshot.get("snapshot_id"),
        },
        game_distribution=snapshot.get("game_distribution"),
    )

"""Same-game research from the deployed model's shared score distribution.

Never infer player dependence from marginal probabilities or multiply leg prices.
Quotes are owner-supplied combined offers, not a sportsbook execution integration.
"""

from collections import Counter, defaultdict
from dataclasses import replace
from decimal import Decimal as D
from hashlib import sha256
from itertools import combinations
import json
from math import prod, sqrt

from jabazi.domain.pricing import decimal_price
from jabazi.models.score_distribution import FEATURES, MARKETS, outcome_probability, score_samples

VERSION = "sgp-joint-0.2.0"
SETTLEMENT = "full_game_including_overtime"


def leg_identity(price):
    market = price.market.removeprefix("alternate_")
    line = str(price.line.normalize()) if price.line is not None else None
    return (price.sport, price.event_id, market, price.participant, price.selection, line)


def leg_id(price):
    return sha256(json.dumps(leg_identity(price)).encode()).hexdigest()[:24]


def _scenarios(model, prices):
    """Use validated inference inputs; never bypass model identity/freshness checks."""
    from jabazi.models.score_distribution import ScoreDistributionModel
    from jabazi.models.nhl_goals import NHLGoalsModel, score_grid, SETTLEMENT as NHL_SETTLEMENT

    estimates = [model.estimate(p) for p in prices]
    if any(e is None for e in estimates):
        raise ValueError("MODEL_INPUTS_UNAVAILABLE")
    snapshots = [e.feature_snapshot for e in estimates]
    first = snapshots[0]
    if any(s["schedule_game_id"] != first["schedule_game_id"] for s in snapshots):
        raise ValueError("MODEL_EVENT_MISMATCH")
    if isinstance(model, ScoreDistributionModel):
        vector = [first["features"][f] for f in FEATURES]
        if any(s["features"] != first["features"] for s in snapshots):
            raise ValueError("MODEL_SCENARIOS_MISALIGNED")
        counts = Counter(score_samples(model.artifact, vector))
        total = sum(counts.values())
        grid = {score: D(count) / total for score, count in counts.items()}
        settlement = SETTLEMENT
    elif isinstance(model, NHLGoalsModel):
        rates = first["regulation_goal_rates"]
        if any(s["regulation_goal_rates"] != rates for s in snapshots):
            raise ValueError("MODEL_SCENARIOS_MISALIGNED")
        raw = score_grid(*rates, model.artifact["overtime_home_probability"])
        total = sum(D(str(m)) for m in raw.values())
        grid = {score: D(str(m)) / total for score, m in raw.items()}
        settlement = NHL_SETTLEMENT
    else:
        raise ValueError("JOINT_SCORE_MODEL_UNAVAILABLE")
    outcomes = []
    for score in grid:
        row = []
        for p, snapshot in zip(prices, snapshots, strict=True):
            result = outcome_probability(
                [score],
                p.market,
                snapshot["canonical_selection"],
                p.line,
                first["home_team"],
                first["away_team"],
                snapshot.get("canonical_participant"),
            )
            if result is None:
                raise ValueError("UNSUPPORTED_MARKET")
            if result["push"]:
                # Dropping tie samples would condition every leg on the moneyline result.
                raise ValueError("PUSH_OR_TIE_REPRICING_UNSUPPORTED")
            row.append(result["win"] == 1)
        outcomes.append(row)
    return outcomes, list(grid.values()), estimates, settlement


def evaluate_same_game(prices, model, *, now, offer=None, player_models=None, joint_player=None):
    """Evaluate 2–4 archived legs and an optional exact, timestamped SGP offer."""
    if now.tzinfo is None:
        raise ValueError("Timezone-aware evaluation time required")
    ids = [leg_id(p) for p in prices]
    result = {
        "engine_version": VERSION,
        "status": "UNAVAILABLE",
        "reasons": [],
        "method": "shared_score_scenarios",
        "legs": [
            {
                "leg_id": i,
                "event_id": p.event_id,
                "sport": p.sport,
                "event": p.event,
                "market": p.market,
                "participant": p.participant,
                "selection": p.selection,
                "line": str(p.line) if p.line is not None else None,
            }
            for i, p in zip(ids, prices, strict=True)
        ],
        "evaluated_at": now.isoformat(),
        "joint_probability": None,
        "expected_roi": None,
        "recommended_stake_units": None,
        "approved_for_betting": False,
        "cash_influence": False,
        "player_props_status": "JOINT_PLAYER_MODEL_UNAVAILABLE",
    }

    def blocked(reason):
        result["reasons"].append(reason)
        return result

    if not 2 <= len(prices) <= 4 or len(set(ids)) != len(ids):
        return blocked("REQUIRE_2_TO_4_DISTINCT_LEGS")
    if len({(p.sport, p.event_id, p.event, p.starts_at) for p in prices}) != 1:
        return blocked("SAME_EVENT_REQUIRED")
    player_ticket = any(p.market not in MARKETS for p in prices)
    if player_ticket and (not player_models or joint_player is None):
        return blocked("JOINT_PLAYER_MODEL_UNAVAILABLE")
    if player_ticket and any(p.market in MARKETS for p in prices):
        return blocked("MIXED_TEAM_PLAYER_JOINT_MODEL_UNAVAILABLE")
    if any(p.in_play or p.starts_at is None or p.starts_at <= now for p in prices):
        return blocked("PREGAME_ONLY")
    if any(
        p.stale
        or not 0 <= (now - p.source_timestamp).total_seconds() <= 120
        or not 0 <= (now - p.observed_at).total_seconds() <= 120
        for p in prices
    ):
        return blocked("STALE_OR_FUTURE_LEG_DATA")
    if model is None and not player_ticket:
        return blocked("JOINT_SCORE_MODEL_UNAVAILABLE")
    try:
        if player_ticket:
            rows, weights, estimates, settlement, evidence = joint_player.scenarios(
                prices, player_models
            )
            result.update(
                method="empirical_residual_rank_checkerboard_copula",
                player_props_status="SHADOW_ONLY",
                player_joint_evidence=evidence,
            )
        else:
            rows, weights, estimates, settlement = _scenarios(
                model, [replace(p, observed_at=now) for p in prices]
            )
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return blocked(str(exc) if isinstance(exc, ValueError) else "INVALID_MODEL_SCENARIOS")
    p = sum((w for row, w in zip(rows, weights) if all(row)), D(0))
    marginals = [
        sum((w for row, w in zip(rows, weights) if row[i]), D(0)) for i in range(len(prices))
    ]
    pairs = []
    for i, j in combinations(range(len(prices)), 2):
        both = sum((w for row, w in zip(rows, weights) if row[i] and row[j]), D(0))
        variance = marginals[i] * (1 - marginals[i]) * marginals[j] * (1 - marginals[j])
        pairs.append(
            {
                "legs": [ids[i], ids[j]],
                "phi": float(both - marginals[i] * marginals[j]) / sqrt(float(variance))
                if variance > 0
                else None,
            }
        )
    # Deliberately a policy haircut, not a claimed calibrated joint confidence interval.
    haircut = min(D(1), sum((e.uncertainty for e in estimates), D(0)))
    adjusted = max(D(0), p - haircut)
    fingerprint = sha256(json.dumps(sorted(ids)).encode()).hexdigest()
    result.update(
        status="PRICE_CHECK",
        candidate_id=fingerprint,
        joint_probability=p,
        expires_from=min(p.source_timestamp for p in prices).isoformat(),
        marginal_probabilities=marginals,
        pairwise_correlations=pairs,
        independence_diagnostic=prod(marginals),
        dependence_lift=p / prod(marginals) if prod(marginals) else None,
        fair_decimal=1 / p if p else None,
        adjusted_joint_probability=adjusted,
        probability_haircut=haircut,
        uncertainty_method="sum_of_leg_policy_haircuts_not_a_CI",
        model_version=estimates[0].model_version,
        settlement=settlement,
        provenance={
            "dataset_hash": estimates[0].feature_snapshot.get("dataset_hash"),
            "state_refreshed_at": estimates[0].feature_snapshot.get("state_refreshed_at"),
            "schedule_game_id": estimates[0].feature_snapshot.get(
                "schedule_game_id", prices[0].event_id
            ),
        },
        limitations=[
            "Joint probabilities have not passed prospective SGP calibration",
            "Only admitted two-prop NFL relationships are modeled; no mixed team/player tickets",
            "No automatic sportsbook combined-quote feed",
        ],
    )
    if p == 0:
        result["status"] = "PASS"
        return blocked("NO_JOINT_WINS_IN_MODEL_SUPPORT")
    if offer is None:
        return blocked("EXACT_COMBINED_QUOTE_REQUIRED")
    # Binding prevents an offer for different alternate lines/legs being reused.
    if (
        offer.get("candidate_id") != fingerprint
        or not offer.get("quote_id")
        or not offer.get("sportsbook")
    ):
        return blocked("COMBINED_QUOTE_IDENTITY_MISMATCH")
    if offer.get("settlement") != settlement:
        return blocked("SPORTSBOOK_SETTLEMENT_CONFIRMATION_REQUIRED")
    from jabazi.models.team_elo import timestamp

    try:
        quoted_at = timestamp(offer["quoted_at"])
        if quoted_at.tzinfo is None or not 0 <= (now - quoted_at).total_seconds() <= 120:
            return blocked("STALE_OR_FUTURE_COMBINED_QUOTE")
        price = decimal_price(offer["decimal_odds"])
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return blocked("INVALID_COMBINED_QUOTE")
    result.update(
        status="RESEARCH_ONLY",
        offered_decimal=price,
        expected_roi=p * price - 1,
        risk_adjusted_roi=adjusted * price - 1,
        research_price_threshold=D("1.05") / adjusted if adjusted else None,
        quote={**offer, "source": "owner_supplied_not_independently_verified"},
    )
    if adjusted * price - 1 < D(".05"):
        result["status"] = "PASS"
        result["reasons"].append("INSUFFICIENT_RISK_ADJUSTED_ROI")
    if len(prices) == 4:
        result["reasons"].append("FOUR_LEG_STRUCTURE_REQUIRES_SEPARATE_REVIEW")
    return result


def scan_candidates(actions, models, *, now, player_models=None):
    """Bounded two-leg research screen; probabilities aren't a profitability ranking."""
    from jabazi.models.player_joint import load_joint_player_model

    joint_player = load_joint_player_model() if player_models else None
    grouped = defaultdict(list)
    for action in actions:
        p = action.price
        if p.market in {"h2h", "spreads", "totals", "team_totals"} or (
            player_models and (p.sport, p.market) in player_models
        ):
            grouped[(p.sport, p.event_id, p.market not in MARKETS)].append(p)
    candidates, blocked, examined = [], Counter(), 0
    for (sport, _, _), prices in sorted(grouped.items()):
        unique = {leg_id(p): p for p in prices}
        for pair in combinations(list(unique.values())[:8], 2):
            examined += 1
            r = evaluate_same_game(
                pair,
                models.get(sport),
                now=now,
                player_models=player_models,
                joint_player=joint_player,
            )
            if r["status"] == "PRICE_CHECK":
                candidates.append(r)
            else:
                blocked.update(r["reasons"])
            if examined >= 300:
                break
        if examined >= 300:
            break
    candidates.sort(key=lambda r: (-r["joint_probability"], r["candidate_id"]))
    return {
        "engine_version": VERSION,
        "status": "RESEARCH_ONLY",
        "approved_for_betting": False,
        "candidates": candidates[:12],
        "pairs_examined": examined,
        "candidates_found": len(candidates),
        "blocked_reasons": dict(blocked),
        "screen_limit": 300,
        "retained_limit": 12,
        "ordering": "joint_hit_probability_not_EV",
        "player_props": "TWO_LEG_NFL_RESEARCH" if joint_player else "JOINT_MODEL_UNAVAILABLE",
    }

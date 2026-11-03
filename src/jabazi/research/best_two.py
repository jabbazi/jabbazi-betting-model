"""Protected two-leg sheet-candidate research lane.

External sheets are discovery evidence only. Each leg must independently survive the
JABBAZI model/reliability gates. Claimed units never become model confidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import math

SOURCE_NAMES=("Bookie Bandit","GG Squad")


@dataclass(frozen=True)
class BestTwoCandidate:
    legs: tuple[dict,dict]
    joint_probability: float | None
    uncertainty_low: float | None
    uncertainty_high: float | None
    method: str
    status: str
    reasons: tuple[str,...]
    requested_stake_units: Decimal = Decimal("2")
    recommended_stake_units: Decimal | None = None
    cash_influence: bool = False


def _source_support(source_rows, action):
    matches=[]
    for row in source_rows:
        p=row.get("payload",row)
        if (
            p.get("sport")==action.get("sport")
            and str(p.get("event_id"))==str(action.get("event_id"))
            and p.get("market")==action.get("market")
            and p.get("selection")==action.get("selection")
            and p.get("line")==action.get("line")
        ):
            matches.append(p)
    return matches


def rank(actions, source_rows):
    ranked=[]
    for action in actions:
        p=action.get("model_probability")
        market=action.get("market_no_vig_probability") or action.get("consensus_probability")
        if p is None or market is None:
            continue
        p=float(p); market=float(market)
        if not 0<p<1 or not 0<market<1:
            continue
        rel=action.get("reliability") or action
        if rel.get("model_lane_decision") in {"PASS","QUARANTINED"}:
            continue
        if rel.get("v5_state")=="QUARANTINED":
            continue
        sources=_source_support(source_rows,action)
        named={s.get("source") for s in sources}
        # Source-unit labels are metadata only. Agreement and independent model edge
        # can improve research priority, but never betting approval.
        independent_agreement=sum(1 for s in sources if s.get("independently_agreed") is True)
        source_score=min(1.0,0.20*len(named)+0.10*independent_agreement)
        uncertainty=float(action.get("uncertainty") or 0)
        edge=p-market
        conservative=edge-uncertainty
        score=conservative+0.02*source_score
        ranked.append({
            **action,
            "sheet_sources":sorted(x for x in named if x),
            "sheet_claimed_units":[str(s.get("claimed_units")) for s in sources if s.get("claimed_units") is not None],
            "sheet_source_score":source_score,
            "conservative_edge":conservative,
            "best_two_score":score,
        })
    return sorted(ranked,key=lambda x:(x["best_two_score"],x["conservative_edge"]),reverse=True)


def build(actions, source_rows):
    candidates=rank(actions,source_rows)
    if len(candidates)<2:
        return BestTwoCandidate((),None,None,None,"unavailable","PRICE_CHECK",("Fewer than two independently supported sheet candidates",))
    # Prefer different events to avoid pretending an SGP is independent.
    pair=None
    for i,a in enumerate(candidates):
        for b in candidates[i+1:]:
            if a["event_id"]!=b["event_id"]:
                pair=(a,b); break
        if pair: break
    if pair is None:
        return BestTwoCandidate((),None,None,None,"same_event_joint_required","WATCH",("Top candidates share an event; aligned scenario evidence required",))
    from jabazi.models.scenario_engine import cross_event_ticket
    ticket=cross_event_ticket(tuple({
        "event_id":leg["event_id"],
        "market":leg["market"],
        "selection":leg["selection"],
        "participant":leg.get("participant"),
        "probability":float(leg["model_probability"]),
        "uncertainty_low":float(leg.get("uncertainty_low") or max(0.001,float(leg["model_probability"])-float(leg.get("uncertainty") or 0))),
        "uncertainty_high":float(leg.get("uncertainty_high") or min(0.999,float(leg["model_probability"])+float(leg.get("uncertainty") or 0))),
    } for leg in pair))
    return BestTwoCandidate(
        tuple(pair),ticket.probability,ticket.uncertainty_low,ticket.uncertainty_high,
        ticket.method,"PRICE_CHECK",
        ("Exact sportsbook combined quote required before EV/stake evaluation",),
    )


def price(candidate, *, decimal_odds, current_exposure_known=False, exposure_capacity_units=None):
    if candidate.status!="PRICE_CHECK" or candidate.joint_probability is None:
        return candidate
    price=float(decimal_odds)
    if not math.isfinite(price) or price<=1:
        raise ValueError("Valid combined decimal quote required")
    breakeven=1/price
    # Size against the conservative lower joint bound, never the point estimate.
    low=float(candidate.uncertainty_low)
    if low<=breakeven:
        return BestTwoCandidate(
            candidate.legs,candidate.joint_probability,candidate.uncertainty_low,
            candidate.uncertainty_high,candidate.method,"PASS",
            candidate.reasons+(f"Conservative joint probability {low:.4f} does not beat break-even {breakeven:.4f}",),
        )
    if not current_exposure_known or exposure_capacity_units is None:
        return BestTwoCandidate(
            candidate.legs,candidate.joint_probability,candidate.uncertainty_low,
            candidate.uncertainty_high,candidate.method,"WATCH",
            ("Positive conservative joint value at quoted price, but current exposure capacity is UNKNOWN",),
        )
    cap=Decimal(str(exposure_capacity_units))
    # User preference is 2u, but ordinary supported 2-leg tickets stay 0.5-1u.
    # 2u is exceptional and requires unusually wide conservative price margin.
    margin=low-breakeven
    target=Decimal("2") if margin>=0.08 else Decimal("1") if margin>=0.04 else Decimal("0.5")
    stake=min(target,cap)
    if stake<=0:
        status="PASS"; reasons=("No current portfolio capacity",)
    else:
        status="BET_CANDIDATE"; reasons=(
            f"Verified quote clears conservative joint break-even by {margin:.4f}",
            "2u is allowed only when the conservative joint margin and exposure capacity justify it",
        )
    return BestTwoCandidate(
        candidate.legs,candidate.joint_probability,candidate.uncertainty_low,
        candidate.uncertainty_high,candidate.method,status,reasons,
        recommended_stake_units=stake,cash_influence=False,
    )

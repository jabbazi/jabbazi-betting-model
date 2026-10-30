"""V5 scenario engine: joint probabilities, uncertainty and concentration.

This module never creates betting approval. It combines already-validated scenario
measures and explicitly labels independence assumptions when events differ.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054):
    if not isinstance(successes, int) or not isinstance(trials, int) or not 0 <= successes <= trials:
        raise ValueError("Invalid binomial evidence")
    if trials == 0:
        return None
    p = successes / trials
    denom = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denom
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return max(0.0, center - radius), min(1.0, center + radius)


@dataclass(frozen=True)
class JointTicket:
    legs: tuple[dict, ...]
    probability: float
    uncertainty_low: float
    uncertainty_high: float
    method: str
    sample_count: int | None
    independence_assumption: bool
    concentration_keys: tuple[str, ...]
    approved_for_betting: bool = False

    @property
    def fair_decimal(self):
        return 1 / self.probability if 0 < self.probability < 1 else None


def same_event_ticket(distribution, legs, *, home, away, event_id):
    result = distribution.joint(legs, home=home, away=away, event_id=event_id)
    joint = float(result["joint_probability"])
    n = int(result["sample_count"])
    successes = round(joint * n)
    interval = wilson_interval(successes, n)
    if interval is None:
        raise ValueError("Missing scenario support")
    keys = []
    for leg in legs:
        participant = leg.get("participant") or leg.get("selection")
        keys.extend((f"event:{event_id}", f"market:{leg['market']}", f"subject:{participant}"))
    return JointTicket(
        tuple(legs),
        joint,
        interval[0],
        interval[1],
        "shared_game_scenarios",
        n,
        False,
        tuple(sorted(set(keys))),
    )


def cross_event_ticket(legs):
    """Compose independent-event marginals only when event IDs are distinct.

    This is deliberately not an SGP correlation estimator. Same-event legs must use
    a shared scenario measure.
    """
    if not 2 <= len(legs) <= 4:
        raise ValueError("Only 2-4 leg research tickets are supported")
    events = [str(leg.get("event_id") or "") for leg in legs]
    if not all(events) or len(set(events)) != len(events):
        raise ValueError("Cross-event composition requires distinct event IDs")
    probabilities = [float(leg["probability"]) for leg in legs]
    if any(not math.isfinite(p) or not 0 < p < 1 for p in probabilities):
        raise ValueError("Invalid marginal probability")
    joint = math.prod(probabilities)
    # Conservative propagation: combine each leg's supplied bounds when present.
    lows = [float(leg.get("uncertainty_low", p)) for leg, p in zip(legs, probabilities)]
    highs = [float(leg.get("uncertainty_high", p)) for leg, p in zip(legs, probabilities)]
    if any(not 0 <= lo <= p <= hi <= 1 for lo, p, hi in zip(lows, probabilities, highs)):
        raise ValueError("Invalid marginal uncertainty")
    keys = []
    for leg in legs:
        participant = leg.get("participant") or leg.get("selection")
        keys.extend((f"event:{leg['event_id']}", f"market:{leg['market']}", f"subject:{participant}"))
    return JointTicket(
        tuple(legs),
        joint,
        math.prod(lows),
        math.prod(highs),
        "distinct_event_product_with_bound_propagation",
        None,
        True,
        tuple(sorted(set(keys))),
    )


def overlap(ticket_a: JointTicket, ticket_b: JointTicket):
    a, b = set(ticket_a.concentration_keys), set(ticket_b.concentration_keys)
    union = a | b
    return {
        "shared_keys": sorted(a & b),
        "jaccard": len(a & b) / len(union) if union else 0.0,
        "same_event": any(key.startswith("event:") for key in a & b),
        "same_subject": any(key.startswith("subject:") for key in a & b),
    }

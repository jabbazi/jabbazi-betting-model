"""Distribution-based threshold and touchdown research, without synthetic fitted inputs."""

from dataclasses import dataclass
from decimal import Decimal as D
import math
from jabazi.domain.pricing import probability, number, value


@dataclass(frozen=True)
class DiscreteDistribution:
    support: tuple[D, ...]
    mass: tuple[D, ...]
    model_version: str
    provenance: str
    approved_for_betting: bool = False

    def __post_init__(self):
        if not self.model_version or not self.provenance:
            raise ValueError("Version and provenance required")
        if not self.support or len(self.support) != len(self.mass):
            raise ValueError("Aligned support and mass required")
        for x in self.support:
            number(x)
        for p in self.mass:
            probability(p)
        if abs(sum(self.mass) - 1) > D("1e-10"):
            raise ValueError("Mass must sum to one")
        if self.approved_for_betting:
            raise ValueError("Research distributions cannot self-approve")

    def threshold(self, line):
        line = number(line)
        over = sum((p for x, p in zip(self.support, self.mass) if x > line), D(0))
        under = sum((p for x, p in zip(self.support, self.mass) if x < line), D(0))
        return {"over": over, "under": under, "push": 1 - over - under}


def empirical(samples, weights, *, model_version, provenance):
    """Samples must come from a documented fitted model or observed research data."""
    return DiscreteDistribution(
        tuple(map(number, samples)), tuple(map(probability, weights)), model_version, provenance
    )


def poisson_count(mean, *, model_version, provenance, max_count=1000):
    mean = float(number(mean))
    if not 0 <= mean <= 100:
        raise ValueError("Count mean outside supported numerical range")
    if not 1 <= max_count <= 10000:
        raise ValueError("Invalid support cap")
    masses = []
    p = math.exp(-mean)
    cumulative = 0
    for k in range(max_count + 1):
        if k:
            p *= mean / k
        masses.append(D(str(p)))
        cumulative += p
        if cumulative >= 1 - 1e-12:
            break
    if cumulative < 1 - 1e-10:
        raise ValueError("Support cap truncates material probability mass")
    # Normalize only numerical tail residue; reject material truncation above.
    total = sum(masses)
    return DiscreteDistribution(
        tuple(D(i) for i in range(len(masses))),
        tuple(p / total for p in masses),
        model_version,
        provenance,
    )


def usage_mixture(distributions, weights, *, model_version, provenance):
    if not distributions or len(distributions) != len(weights):
        raise ValueError("Usage scenarios required")
    weights = list(map(probability, weights))
    if abs(sum(weights) - 1) > D("1e-12"):
        raise ValueError("Scenario weights must sum to one")
    aggregate = {}
    for distribution, w in zip(distributions, weights):
        for x, p in zip(distribution.support, distribution.mass):
            aggregate[x] = aggregate.get(x, D(0)) + w * p
    return DiscreteDistribution(
        tuple(sorted(aggregate)),
        tuple(aggregate[x] for x in sorted(aggregate)),
        model_version,
        provenance,
    )


def anytime_td(team_expected_touchdowns, player_scoring_share, *, model_version, provenance):
    """Poisson thinning baseline: scoring TDs, never passing-TD/yardage proxies.

    The team TD forecast and player scoring share must be independently fitted
    and validated before this framework could support production use.
    """
    rate = number(team_expected_touchdowns) * probability(player_scoring_share)
    if rate < 0 or not model_version or not provenance:
        raise ValueError("Documented nonnegative scoring inputs required")
    p = D(str(-math.expm1(-float(rate))))
    return {
        "probability": p,
        "fair_decimal": 1 / p if p else None,
        "model_version": model_version,
        "provenance": provenance,
        "approved_for_betting": False,
    }


def alternatives(distribution, offers, *, uncertainty=0, required_roi=0):
    """Price each offered rung separately; never assume a safer line is better."""
    result = []
    for offer in offers:
        probabilities = distribution.threshold(offer["line"])
        side = offer["side"]
        if side not in {"over", "under"}:
            raise ValueError("Side must be over or under")
        result.append(
            {
                "offer": offer,
                "probabilities": probabilities,
                "valuation": value(
                    probabilities[side],
                    offer["market_probability"],
                    offer["decimal_odds"],
                    uncertainty=uncertainty,
                    required_roi=required_roi,
                    push=probabilities["push"],
                ),
                "status": "RESEARCH_ONLY",
            }
        )
    return sorted(result, key=lambda row: row["valuation"].expected_roi, reverse=True)

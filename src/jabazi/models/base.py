from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from jabazi.domain.shopping import PriceCard


@dataclass(frozen=True)
class ModelEstimate:
    probability: Decimal
    uncertainty: Decimal
    model_name: str
    model_version: str
    feature_snapshot: dict[str, object]
    approved_for_betting: bool = False

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.probability <= Decimal("1"):
            raise ValueError("Probability must be between 0 and 1")
        if not Decimal("0") <= self.uncertainty <= Decimal("1"):
            raise ValueError("Uncertainty must be between 0 and 1")


class ProbabilityModel(ABC):
    sport: str
    supported_markets: frozenset[str]

    @abstractmethod
    def estimate(self, price: PriceCard) -> ModelEstimate | None:
        """Return None rather than guessing when inputs or market support are insufficient."""
        raise NotImplementedError

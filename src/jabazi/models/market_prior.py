"""Market benchmark model.

This is a calibrated reference prior, not an independent edge model. It is useful
for ranking disagreement and as the prior for sport models, but is never approved
to generate BET_NOW by itself.
"""

from decimal import Decimal

from jabazi.domain.shopping import PriceCard
from .base import ModelEstimate, ProbabilityModel


class MarketPriorModel(ProbabilityModel):
    sport = "*"
    supported_markets = frozenset({"h2h", "spreads", "totals", "outrights"})

    def estimate(self, price: PriceCard) -> ModelEstimate:
        dispersion = min(Decimal("1"), price.sportsbook_disagreement * Decimal("4"))
        uncertainty = Decimal("0.05") + dispersion
        return ModelEstimate(
            probability=price.consensus_probability,
            uncertainty=min(Decimal("0.50"), uncertainty),
            model_name="market_prior",
            model_version="1.0.0",
            feature_snapshot={
                "consensus_probability": str(price.consensus_probability),
                "sportsbook_disagreement": str(price.sportsbook_disagreement),
                "books": {book: str(odds) for book, odds in price.book_prices.items()},
            },
            approved_for_betting=False,
        )

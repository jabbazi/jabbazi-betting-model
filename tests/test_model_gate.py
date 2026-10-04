import unittest
from datetime import datetime, timezone
from decimal import Decimal

from jabazi.domain.models import DataQuality, Decision, Quote
from jabazi.domain.recommendation import recommend_price
from jabazi.domain.risk import RiskPolicy
from jabazi.domain.shopping import build_price_cards
from jabazi.models.market_prior import MarketPriorModel


class ModelGateTests(unittest.TestCase):
    def test_market_prior_cannot_create_bet_now(self):
        now = datetime.now(timezone.utc)
        quotes = (
            Quote(
                "1",
                "e",
                "h2h",
                "A",
                "draftkings",
                Decimal("2.2"),
                None,
                now,
                now,
                DataQuality.DELAYED,
                "nfl",
                "A @ B",
                now.replace(year=2027),
            ),
            Quote(
                "2",
                "e",
                "h2h",
                "B",
                "draftkings",
                Decimal("1.75"),
                None,
                now,
                now,
                DataQuality.DELAYED,
                "nfl",
                "A @ B",
                now.replace(year=2027),
            ),
        )
        card = next(c for c in build_price_cards(quotes, now=now) if c.selection == "A")
        estimate = MarketPriorModel().estimate(card)
        action = recommend_price(
            card,
            RiskPolicy(Decimal("1000")),
            estimate.probability,
            estimate.uncertainty,
            model_validated=estimate.approved_for_betting,
        )
        self.assertEqual(action.decision, Decision.WATCH)
        self.assertEqual(action.stake, Decimal("0"))

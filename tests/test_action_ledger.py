import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jabazi.domain.models import DataQuality, Quote
from jabazi.domain.recommendation import recommend_price
from jabazi.domain.risk import RiskPolicy
from jabazi.domain.shopping import build_price_cards
from jabazi.persistence.sqlite import Ledger


class ActionLedgerTests(unittest.TestCase):
    def test_identical_recommendation_is_recorded_once(self):
        now = datetime.now(timezone.utc)
        quotes = (
            Quote(
                "1",
                "e",
                "h2h",
                "A",
                "draftkings",
                Decimal("2.1"),
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
                Decimal("1.8"),
                None,
                now,
                now,
                DataQuality.DELAYED,
                "nfl",
                "A @ B",
                now.replace(year=2027),
            ),
        )
        action = recommend_price(build_price_cards(quotes, now=now)[0], RiskPolicy(Decimal("1000")))
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "ledger.db")
            self.assertTrue(ledger.record_action_card(action, now))
            self.assertFalse(ledger.record_action_card(action, now))
            self.assertEqual(
                ledger.connection.execute("SELECT COUNT(*) FROM action_cards").fetchone()[0], 1
            )
            ledger.close()

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jabazi.domain.models import Candidate, DataQuality, Quote
from jabazi.domain.risk import RiskPolicy
from jabazi.persistence.sqlite import Ledger
from jabazi.scanner.service import ScanCandidate, Scanner

NOW = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)


class ScannerTests(unittest.TestCase):
    def test_same_payload_same_day_is_idempotent_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.db"
            ledger = Ledger(path)
            q1 = Quote(
                "q1",
                "e1",
                "ml",
                "home",
                "draftkings",
                Decimal("2.10"),
                None,
                NOW,
                NOW,
                DataQuality.REALTIME,
            )
            q2 = Quote(
                "q2",
                "e1",
                "ml",
                "away",
                "draftkings",
                Decimal("1.80"),
                None,
                NOW,
                NOW,
                DataQuality.REALTIME,
            )
            item = ScanCandidate(
                Candidate("e1", "ml", "home", Decimal("0.56"), Decimal("0"), "v1", (q1,)), (q2,)
            )
            scanner = Scanner(ledger, RiskPolicy(bankroll=Decimal("1000")), "America/Los_Angeles")
            self.assertEqual(len(scanner.run((item,), NOW)), 1)
            self.assertEqual(scanner.run((item,), NOW), [])
            ledger.close()
            reopened = Ledger(path)
            self.assertEqual(reopened.recommendation_count(), 1)
            reopened.close()


if __name__ == "__main__":
    unittest.main()

import unittest
from decimal import Decimal

from jabazi.domain.performance import brier_score, calibration_bucket, price_clv, probability_clv


class PerformanceTests(unittest.TestCase):
    def test_clv_is_positive_when_entry_beats_close(self):
        self.assertGreater(price_clv(Decimal("2.10"), Decimal("1.90")), 0)
        self.assertGreater(probability_clv(Decimal("2.10"), Decimal("1.90")), 0)

    def test_brier_score(self):
        score = brier_score([(Decimal("0.8"), 1), (Decimal("0.3"), 0)])
        self.assertEqual(score, Decimal("0.065"))

    def test_bucket(self):
        self.assertEqual(calibration_bucket(Decimal("0.62")), "60-65")

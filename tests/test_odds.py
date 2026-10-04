import unittest
from decimal import Decimal

from jabazi.domain.odds import (
    OddsError,
    american_to_decimal,
    decimal_to_american,
    expected_value,
    fractional_kelly,
    implied_probability,
    proportional_no_vig,
)


class OddsTests(unittest.TestCase):
    def test_american_round_trip(self):
        for price in (Decimal("100"), Decimal("150"), Decimal("-110"), Decimal("-200")):
            self.assertEqual(decimal_to_american(american_to_decimal(price)), price)

    def test_invalid_american_dead_zone(self):
        with self.assertRaises(OddsError):
            american_to_decimal(Decimal("-99"))

    def test_implied_and_no_vig(self):
        raw = [implied_probability(Decimal("1.91")), implied_probability(Decimal("1.91"))]
        fair = proportional_no_vig(raw)
        self.assertAlmostEqual(fair[0], Decimal("0.5"), places=24)
        self.assertAlmostEqual(fair[1], Decimal("0.5"), places=24)

    def test_ev_and_kelly(self):
        self.assertEqual(expected_value(Decimal("0.55"), Decimal("2")), Decimal("0.10"))
        self.assertEqual(
            fractional_kelly(Decimal("0.55"), Decimal("2"), Decimal("0.25")), Decimal("0.0250")
        )


if __name__ == "__main__":
    unittest.main()

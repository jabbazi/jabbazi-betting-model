import unittest
from datetime import datetime, timezone
from decimal import Decimal

from jabazi.domain.decision import evaluate
from jabazi.domain.models import Candidate, DataQuality, Decision, Quote
from jabazi.domain.risk import RiskPolicy

NOW = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)


def quote(
    identifier: str,
    book: str,
    selection: str,
    price: str,
    quality: DataQuality = DataQuality.REALTIME,
) -> Quote:
    return Quote(
        identifier, "event-1", "moneyline", selection, book, Decimal(price), None, NOW, NOW, quality
    )


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.policy = RiskPolicy(bankroll=Decimal("1000"))
        self.target = (
            quote("a", "draftkings", "home", "2.10"),
            quote("b", "fanduel", "home", "2.05"),
        )
        self.other = (
            quote("c", "draftkings", "away", "1.80"),
            quote("d", "fanduel", "away", "1.83"),
        )

    def candidate(self, probability: str, uncertainty: str = "0") -> Candidate:
        return Candidate(
            "event-1",
            "moneyline",
            "home",
            Decimal(probability),
            Decimal(uncertainty),
            "baseline-v1",
            self.target,
            model_validated=True,
        )

    def test_bet_when_adjusted_ev_and_capacity_clear(self):
        result = evaluate(self.candidate("0.55"), self.other, self.policy, Decimal("0"), NOW)
        self.assertEqual(result.decision, Decision.BET_NOW)
        self.assertGreater(result.stake, 0)

    def test_uncertainty_can_force_pass(self):
        result = evaluate(
            self.candidate("0.55", "0.15"), self.other, self.policy, Decimal("0"), NOW
        )
        self.assertEqual(result.decision, Decision.PASS)

    def test_fixture_price_is_never_executable(self):
        candidate = Candidate(
            "event-1",
            "moneyline",
            "home",
            Decimal("0.60"),
            Decimal("0"),
            "fixture",
            (quote("x", "draftkings", "home", "2.1", DataQuality.FIXTURE),),
            model_validated=True,
        )
        result = evaluate(candidate, self.other, self.policy, Decimal("0"), NOW)
        self.assertEqual(result.decision, Decision.WAIT)
        self.assertEqual(result.stake, Decimal("0"))

    def test_exposure_ceiling_vetoes(self):
        result = evaluate(self.candidate("0.65"), self.other, self.policy, Decimal("200"), NOW)
        self.assertEqual(result.decision, Decision.PASS)


if __name__ == "__main__":
    unittest.main()

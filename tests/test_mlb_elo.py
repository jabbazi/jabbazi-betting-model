import json
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jabazi.domain.shopping import PriceCard
from jabazi.models.mlb_elo import MlbMoneylineEloModel, train_mlb_elo


class MlbEloTests(unittest.TestCase):
    def test_trainer_stays_shadow_without_market_comparison(self):
        rows = []
        for season in (2023, 2024, 2025):
            for index in range(600):
                home = "A" if index % 2 else "B"
                away = "B" if home == "A" else "A"
                rows.append(
                    {
                        "game_id": f"{season}-{index}",
                        "starts_at": f"{season}-07-01T00:00:00Z",
                        "season": season,
                        "away_team": away,
                        "home_team": home,
                        "away_score": 2,
                        "home_score": 3 if home == "A" else 1,
                        "away_moneyline": None,
                        "home_moneyline": None,
                    }
                )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "games.json"
            artifact = Path(directory) / "model.json"
            source.write_text(json.dumps({"games": rows}), encoding="utf-8")
            result = train_mlb_elo(source, artifact)
            self.assertFalse(result.approved_for_betting)
            self.assertIn("fewer than 300 no-vig market comparisons", result.validation_reasons)
            model = MlbMoneylineEloModel(artifact)
            now = datetime.now(UTC)
            card = PriceCard(
                "baseball_mlb",
                "1",
                "B @ A",
                "h2h",
                None,
                "A",
                None,
                {"DraftKings": Decimal(2)},
                "DraftKings",
                Decimal(2),
                Decimal("0.5"),
                Decimal(0),
                Decimal(0),
                False,
                False,
                ("q",),
                now,
                now,
                now,
            )
            estimate = model.estimate(card)
            self.assertIsNotNone(estimate)
            self.assertFalse(estimate.approved_for_betting)
            self.assertGreater(estimate.probability, Decimal("0.5"))


if __name__ == "__main__":
    unittest.main()

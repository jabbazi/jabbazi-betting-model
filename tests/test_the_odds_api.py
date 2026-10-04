import json
import unittest
from decimal import Decimal

from jabazi.domain.models import DataQuality
from jabazi.providers.the_odds_api import TheOddsApiProvider


class TheOddsApiTests(unittest.TestCase):
    def test_book_level_timestamp_is_retained_and_never_replaced_with_now(self):
        from datetime import datetime, timezone

        payload = [
            {
                "id": "e",
                "bookmakers": [
                    {
                        "key": "espnbet",
                        "last_update": "2026-09-22T12:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [{"name": "A", "price": 2}, {"name": "B", "price": 2}],
                            }
                        ],
                    }
                ],
            }
        ]
        provider = TheOddsApiProvider(
            "baseball_mlb",
            api_key="TEST_ONLY",
            transport=lambda url: (json.dumps(payload).encode(), {}),
        )
        batch = provider.fetch()
        self.assertEqual(
            batch.quotes[0].source_timestamp, datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        )
        self.assertIn("espnbet", provider.bookmakers)
        del payload[0]["bookmakers"][0]["last_update"]
        with self.assertRaises(ValueError):
            provider.fetch()

    def test_normalizes_without_exposing_key(self):
        payload = [
            {
                "id": "event1",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "markets": [
                            {
                                "key": "spreads",
                                "last_update": "2026-08-23T20:00:00Z",
                                "outcomes": [
                                    {"name": "Home", "price": 1.91, "point": -1.5},
                                    {"name": "Away", "price": 1.91, "point": 1.5},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        seen_url = []

        def transport(url):
            seen_url.append(url)
            return json.dumps(payload).encode(), {"x-requests-remaining": "499"}

        provider = TheOddsApiProvider("baseball_mlb", api_key="test-secret", transport=transport)
        batch = provider.fetch()
        self.assertEqual(len(batch.quotes), 2)
        self.assertEqual(batch.quotes[0].line, Decimal("-1.5"))
        self.assertEqual(batch.quotes[0].quality, DataQuality.DELAYED)
        self.assertNotIn("test-secret", repr(batch))
        self.assertIn("test-secret", seen_url[0])


if __name__ == "__main__":
    unittest.main()

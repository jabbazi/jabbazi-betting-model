import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jabazi.domain.models import DataQuality, Decision, Quote
from jabazi.domain.recommendation import recommend_price
from jabazi.domain.risk import RiskPolicy
from jabazi.domain.shopping import build_price_cards

NOW = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)


def q(identifier, book, selection, price, line, market="player_points", age=0):
    return Quote(
        identifier,
        "event",
        market,
        selection,
        book,
        Decimal(price),
        Decimal(line) if line is not None else None,
        NOW,
        NOW - timedelta(seconds=age),
        DataQuality.DELAYED,
        "basketball_wnba",
        "Away @ Home",
        NOW + timedelta(hours=2),
    )


class ShoppingTests(unittest.TestCase):
    def test_prop_line_shop_does_not_mix_alternate_rungs(self):
        quotes = (
            q("1", "draftkings", "A Player|Over", "1.91", "19.5"),
            q("2", "draftkings", "A Player|Under", "1.91", "19.5"),
            q("3", "fanduel", "A Player|Over", "2.05", "19.5"),
            q("4", "fanduel", "A Player|Under", "1.80", "19.5"),
            q("5", "fanduel", "A Player|Over", "2.40", "21.5"),
            q("6", "fanduel", "A Player|Under", "1.55", "21.5"),
        )
        cards = build_price_cards(quotes, now=NOW)
        over_19 = next(c for c in cards if c.selection == "Over" and c.line == Decimal("19.5"))
        self.assertEqual(over_19.best_book, "FanDuel")
        self.assertEqual(over_19.best_decimal, Decimal("2.05"))
        self.assertEqual(set(over_19.book_prices), {"DraftKings", "FanDuel"})

    def test_unmodeled_positive_discrepancy_is_watch_not_bet(self):
        quotes = (
            q("1", "draftkings", "Over", "1.91", "8.5", "totals"),
            q("2", "draftkings", "Under", "1.91", "8.5", "totals"),
            q("3", "fanduel", "Over", "2.10", "8.5", "totals"),
            q("4", "fanduel", "Under", "1.75", "8.5", "totals"),
        )
        card = next(c for c in build_price_cards(quotes, now=NOW) if c.selection == "Over")
        action = recommend_price(card, RiskPolicy(Decimal("1000")))
        self.assertEqual(action.decision, Decision.WATCH)
        self.assertEqual(action.stake, Decimal("0"))

    def test_stale_price_is_excluded_from_consensus(self):
        quotes = (
            q("1", "draftkings", "Over", "2.10", "8.5", "totals", age=300),
            q("2", "draftkings", "Under", "1.75", "8.5", "totals", age=300),
        )
        self.assertEqual(build_price_cards(quotes, now=NOW), [])

    def test_suspended_sentinel_price_is_quarantined(self):
        quotes = (
            q("1", "draftkings", "Over", "1.0", "8.5", "totals"),
            q("2", "draftkings", "Under", "1.91", "8.5", "totals"),
            q("3", "fanduel", "Over", "2.0", "8.5", "totals"),
            q("4", "fanduel", "Under", "1.8", "8.5", "totals"),
        )
        cards = build_price_cards(quotes, now=NOW)
        over = next(card for card in cards if card.selection == "Over")
        self.assertEqual(over.book_prices, {"FanDuel": Decimal("2.0")})

    def test_in_play_market_waits(self):
        quotes = (
            q("1", "draftkings", "Over", "2.10", "8.5", "totals"),
            q("2", "draftkings", "Under", "1.75", "8.5", "totals"),
        )
        quotes = tuple(replace(quote, commence_time=NOW - timedelta(minutes=5)) for quote in quotes)
        cards = build_price_cards(quotes, now=NOW)
        action = recommend_price(
            cards[0], RiskPolicy(Decimal("1000")), Decimal("0.60"), model_validated=True
        )
        self.assertEqual(action.decision, Decision.WAIT)
        self.assertIn("in-play", action.reason)

    def test_same_sign_alternate_spread_is_not_devigged(self):
        quotes = (
            q("1", "fanduel", "Team A", "15", "-8.5", "alternate_spreads"),
            q("2", "fanduel", "Team B", "16", "-8.5", "alternate_spreads"),
        )
        self.assertEqual(build_price_cards(quotes, now=NOW), [])

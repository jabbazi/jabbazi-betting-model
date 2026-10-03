import unittest
from decimal import Decimal

from jabazi.domain.arbitrage import find_arbitrage
from jabazi.domain.shopping import PriceCard


def card(selection, book, odds, market="h2h", line=None):
    return PriceCard(
        "nfl",
        "e",
        "Rams @ Seahawks",
        market,
        None,
        selection,
        Decimal(line) if line is not None else None,
        {book: Decimal(odds)},
        book,
        Decimal(odds),
        Decimal("0.5"),
        Decimal("0"),
        Decimal("0"),
        False,
        False,
        (selection,),
    )


class ArbitrageTests(unittest.TestCase):
    def test_two_way_exact_stakes(self):
        opportunities = find_arbitrage(
            [card("Rams", "DraftKings", "2.10"), card("Seahawks", "FanDuel", "2.00")], Decimal("20")
        )
        self.assertEqual(len(opportunities), 1)
        arb = opportunities[0]
        self.assertGreater(arb.guaranteed_profit, Decimal("0.47"))
        self.assertEqual(sum(leg.stake for leg in arb.legs), Decimal("20"))

    def test_no_arb(self):
        self.assertEqual(
            find_arbitrage(
                [card("A", "DraftKings", "1.80"), card("B", "FanDuel", "1.90")], Decimal("20")
            ),
            [],
        )

    def test_same_sign_alternate_spreads_are_not_arbitrage(self):
        self.assertEqual(
            find_arbitrage(
                [
                    card("Team A", "DraftKings", "15", "alternate_spreads", "-8.5"),
                    card("Team B", "FanDuel", "16", "alternate_spreads", "-8.5"),
                ],
                Decimal("20"),
            ),
            [],
        )

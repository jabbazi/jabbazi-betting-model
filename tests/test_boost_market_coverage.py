"""Synthetic quote fixtures. No credentials or live sportsbook requests."""
from datetime import UTC, date, datetime

from jabazi.boost_market_coverage import summarize_prop_markets


def offer(game, book, market, *, two_sided=True, kind="over_under"):
    prices = ({"type": "over_under", "over_odds": -110,
               "under_odds": -115 if two_sided else None}
              if kind == "over_under"
              else {"type": "milestone", "odds": 210})
    return {
        "sport": "basketball_nba", "game_id": game, "vendor": "BALLDONTLIE",
        "raw": {"game_id": game, "vendor": book, "player_id": 313,
                "prop_type": market, "line_value": "22.5",
                "market": prices,
                "private_player_name": "SECRET_PERSON",
                "deeplinks": {"url": "PRIVATE_SPORTSBOOK_LINK"}},
    }


def test_breadth_counts_distinct_games_and_books_not_raw_prices():
    evidence = [
        offer(123, "draftkings", "points"),
        offer(123, "fanduel", "points", two_sided=False),
        offer(234, "draftkings", "points"),
        offer(234, "draftkings", "threes", kind="milestone"),
    ]
    result = summarize_prop_markets(evidence)
    assert result["market_types_seen"] == 2
    assert result["classification_complete"] is True
    assert result["markets"]["points"] == {
        "accepted_quote_rows": 3, "games_with_market": 2,
        "distinct_bookmakers": 2, "over_under_rows": 3,
        "two_sided_rows": 2, "milestone_rows": 0,
    }
    assert result["markets"]["threes"]["milestone_rows"] == 1
    assert result["all_eligible_markets_verified"] is False
    assert result["executable_bookmaker_quotes_verified"] is False
    assert "SECRET_PERSON" not in str(result)
    assert "PRIVATE_SPORTSBOOK_LINK" not in str(result)
    assert "draftkings" not in str(result)
    assert "fanduel" not in str(result)
    assert "313" not in str(result)


def test_no_rows_never_claim_complete_slate_or_model():
    result = summarize_prop_markets(())
    assert result["market_types_seen"] == 0
    assert result["markets"] == {}
    assert result["status"] == "OBSERVED_ONLY"
    assert result["player_hit_probabilities_verified"] is False
    assert result["all_eligible_markets_verified"] is False


def test_untrusted_market_label_never_gets_echoed():
    item = offer(123, "some-book", "PROVIDER:PRIVATE_KEY")
    result = summarize_prop_markets([item])
    assert result["classification_complete"] is False
    assert result["unclassified_rows"] == 1
    assert "PRIVATE_KEY" not in str(result)


def test_missing_book_game_or_market_refuses_classification():
    for edit in (
        ("game_id", None),
        ("game_id", True),
        ("raw", {}),
        ("raw", "invalid"),
    ):
        item = offer(123, "draftkings", "points")
        item[edit[0]] = edit[1]
        result = summarize_prop_markets([item])
        assert result["classification_complete"] is False
        assert result["markets"] == {}


def test_report_does_not_make_network_requests():
    from tools.boost_live_acceptance import audit_sport

    class Provider:
        def __init__(self):
            self.calls = []
        def fetch_all_pages(self, sport, resource, params, *, max_pages):
            self.calls.append((sport, resource))
            if resource == "games":
                return {
                    "data": [{"id": 123, "date": "2026-10-28",
                              "datetime": "2026-10-28T20:00:00Z",
                              "status_state": "scheduled"}],
                    "pages": 1, "complete": True,
                }
            return {
                "data": [
                    {"id": 200, "game_id": 123, "player_id": 313,
                     "vendor": "draftkings", "prop_type": "points",
                     "line_value": "20.5",
                     "market": {"type": "over_under", "over_odds": -110,
                                "under_odds": -110},
                     "updated_at": datetime.now(UTC).isoformat()},
                ],
                "pages": 1, "complete": True,
            }

    provider = Provider()
    report = audit_sport(
        provider, sport="NBA", calendar_date=date(2026, 10, 28),
        observed_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
    )
    assert provider.calls == [("nba", "games"), ("nba", "props")]
    assert report["observed_market_breadth"]["markets"]["points"]["games_with_market"] == 1
    assert report["observed_market_breadth"]["markets"]["points"]["distinct_bookmakers"] == 1
    assert report["production_approved"] is False
    assert report["recommendation"] == "PASS"

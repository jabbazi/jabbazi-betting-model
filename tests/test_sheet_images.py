import io

from PIL import Image

from jabazi.discord_sheets import parse_command
from jabazi.sheet_images import grouped_rows, odds, percentage, render_card


def record():
    return {
        "payload": {
            "completed_at": "2026-09-23T03:05:00+00:00",
            "healthy": True,
            "rows": [
                {
                    "sport": "americanfootball_nfl",
                    "event": "Example Away @ Example Home",
                    "market": "h2h",
                    "selection": "Example Home",
                    "line": None,
                    "book": "Example Book",
                    "decimal_odds": "1.91",
                    "market_no_vig_probability": "0.51",
                    "research_probability": None,
                    "price_time_utc": "2026-09-23T03:04:00+00:00",
                    "reason": "No validated independent model probability",
                }
            ],
        }
    }


def test_probability_and_price_formatting_does_not_invent_estimates():
    for value in (None, "bad", "NaN", "Infinity", -1, 1.1):
        assert percentage(value) == "Unavailable"
    assert percentage(0.625) == "62.5%"
    assert odds(1.5) == "-200"
    assert odds(3) == "+200"


def test_nfl_cards_are_three_distinct_categories_and_paginate():
    data = record()
    assert list(map(len, grouped_rows(data, "nfl"))) == [1, 0, 0]
    data["payload"]["rows"] *= 25
    for page in (1, 2, 3):
        for group in range(3):
            output = render_card(data, "nfl", group, page=page)
            image = Image.open(io.BytesIO(output))
            assert image.format == "PNG"
            assert image.width == 1200 and 400 < image.height < 2000
            assert len(output) < 7_000_000
    assert parse_command("!cheatsheets nfl 2") == ("sheets", ("nfl",), 2)
    assert parse_command("!cheatsheets nfl 0") is None


def test_anytime_tds_not_mixed_with_other_touchdown_markets():
    data = record()
    base = data["payload"]["rows"][0]
    data["payload"]["rows"] = [
        base | {"market": "player_anytime_td"},
        base | {"market": "player_pass_tds"},
    ]
    assert list(map(len, grouped_rows(data, "nfl"))) == [0, 1, 1]


def test_cfb_player_rows_never_render():
    data = record()
    data["payload"]["rows"][0].update(sport="americanfootball_ncaaf", market="player_pass_yds")
    assert grouped_rows(data, "cfb") == [[], [], []]

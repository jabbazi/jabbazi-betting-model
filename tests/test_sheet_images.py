import io
from datetime import UTC, datetime

from PIL import Image

from jabazi.discord_sheets import parse_command
from jabazi.sheet_images import (
    grouped_rows,
    odds,
    percentage,
    render_card,
    slate_blocks,
    page_count,
    supported_rows,
    compact_selection,
)

AT = datetime(2026, 9, 23, 3, 5, tzinfo=UTC)


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
    base = modeled_row()
    data["payload"]["rows"] = [
        base | {"event_id": str(i), "event": f"Away {i} @ Home {i}"} for i in range(25)
    ]
    assert page_count(data, "nfl", 0, now=AT) == 2
    for page in (1, 2, 3):
        for group in range(3):
            output = render_card(data, "nfl", group, page=page, now=AT)
            image = Image.open(io.BytesIO(output))
            assert image.format == "PNG"
            assert image.width == 1080 and 400 < image.height < 8000
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


def test_duplicate_rungs_do_not_crowd_out_other_games_and_doubleheaders_stay_separate():
    data = record()
    base = data["payload"]["rows"][0]
    data["payload"]["rows"] = [
        base | {"event_id": "game-1", "market": "spreads", "line": line, "book_count": count}
        for line, count in [(1.5, 1), (2.5, 5), (3.5, 1)]
        for _ in range(10)
    ]
    data["payload"]["rows"].append(base | {"event_id": "game-2"})
    blocks = slate_blocks(data, "nfl", 0)
    assert len(blocks) == 2
    first = next(b for b in blocks if b["event_id"] == "game-1")
    assert len(first["rows"]) == 1
    assert first["rows"][0]["line"] == 2.5
    assert {b["event_id"] for b in blocks} == {"game-1", "game-2"}


def test_games_without_fresh_prices_remain_visible_and_do_not_gain_probabilities():
    data = record()
    data["payload"]["slate_events"] = [
        {
            "sport": "americanfootball_nfl",
            "event_id": "missing",
            "event": "Missing odds game",
            "starts_at_utc": "2026-09-24T01:00:00Z",
        }
    ]
    blocks = slate_blocks(data, "nfl", 0)
    missing = next(b for b in blocks if b["event"] == "Missing odds game")
    assert missing["rows"] == []
    assert len(blocks) == 2


def test_all_qualifying_games_are_delivered_without_requesting_extra_pages():
    import asyncio
    from types import SimpleNamespace
    from jabazi.discord_bot import BotConfig, build_client

    data = record()
    base = modeled_row()
    data["payload"]["rows"] = [
        base | {"event_id": str(i), "event": f"A{i} @ B{i}"} for i in range(27)
    ]
    sent = []

    async def exercise():
        client = build_client(BotConfig(1, 2, 3, 4, frozenset()), None)

        async def send(**kwargs):
            sent.extend(f.filename for f in kwargs["files"])
            return SimpleNamespace(id=1)

        await client.send_sheets(SimpleNamespace(send=send), data, ("nfl",), now=AT)
        await client.close()

    asyncio.run(exercise())
    assert len(sent) == 4
    assert "jabbazi-nfl-1-page-2.png" in sent


def modeled_row(**changes):
    base = record()["payload"]["rows"][0]
    return (
        base
        | {
            "event_id": "one",
            "starts_at_utc": "2026-09-24T01:00:00Z",
            "research_probability": "0.60",
            "market_no_vig_probability": "0.50",
            "uncertainty": "0.08",
            "decimal_odds": "2.0",
            "model_version": "SYNTHETIC_TEST_ONLY",
            "executable": True,
            "book_count": 3,
        }
        | changes
    )


def test_shortlist_compares_all_markets_once_per_game_by_value_not_highest_hit_rate():
    from jabazi.sheet_images import shortlist_rows

    data = record()
    data["payload"]["rows"] = [
        modeled_row(research_probability="0.85", decimal_odds="1.15"),
        modeled_row(market="spreads", line=1.5, research_probability="0.70", decimal_odds="1.40"),
        modeled_row(market="alternate_totals", selection="Under", line=8.5),
    ] * 8
    selected = shortlist_rows(data, "nfl", 0)
    assert len(selected) == 1
    assert selected[0]["best"]["market"] == "alternate_totals"
    assert selected[0]["edge"] == __import__("pytest").approx(0.10)
    assert selected[0]["status"] == "WATCH"


def test_unavailable_or_stale_game_is_preserved_but_cannot_become_a_best_pick():
    from jabazi.sheet_images import shortlist_rows

    data = record()
    data["payload"]["rows"] = [
        modeled_row(event_id="old", price_time_utc="2026-09-23T02:00:00Z"),
        modeled_row(event_id="missing", model_version=None),
        modeled_row(event_id="bad", research_probability="NaN"),
    ]
    rows = shortlist_rows(data, "nfl", 0)
    assert len(rows) == 3 and all(r["best"] is None and r["edge"] is None for r in rows)
    assert Image.open(io.BytesIO(render_card(data, "nfl", 0))).height < 700


def test_unmodeled_props_show_neutral_market_references_without_fake_model_edge():
    from jabazi.sheet_images import shortlist_rows, selection_label

    data = record()
    data["payload"]["rows"] = [
        modeled_row(
            participant="Example Player",
            market="player_reception_yds",
            selection="Over",
            line=40.5,
            research_probability=None,
            model_version=None,
        ),
        modeled_row(
            participant="Example Player",
            market="player_rush_yds",
            selection="Over",
            line=10.5,
            research_probability=None,
            model_version=None,
        ),
    ]
    rows = shortlist_rows(data, "nfl", 1)
    assert len(rows) == 1 and rows[0]["best"] is None and rows[0]["edge"] is None
    assert rows[0]["reference"] is not None
    assert "UNRATED" in selection_label(rows[0]["reference"], reference=True)


def test_image_lists_exclude_passes_and_unmodeled_references_and_keep_doubleheaders():
    data = record()
    data["payload"]["rows"] = [
        modeled_row(event_id="game-one"),
        modeled_row(event_id="game-one", market="spreads", line=1.5, decimal_odds="1.1"),
        modeled_row(event_id="game-two", starts_at_utc="2026-09-24T03:00:00Z"),
        modeled_row(event_id="no-edge", decimal_odds="1.1"),
        modeled_row(event_id="no-model", model_version=None),
        modeled_row(event_id="stale", price_stale=True),
    ]
    rows = supported_rows(data, "nfl", 0, now=AT)
    assert {r["event_id"] for r in rows} == {"game-one", "game-two"}
    assert all(r["best"]["market"] == "h2h" for r in rows)
    assert len(supported_rows(data, "nfl", 0, now=AT.replace(minute=6))) == 0
    from unittest.mock import patch
    from PIL import ImageDraw

    original = ImageDraw.ImageDraw.text
    labels = []

    def capture(self, xy, text, *args, **kwargs):
        labels.append(text)
        return original(self, xy, text, *args, **kwargs)

    # Previously supplied rows cannot leak expired selections into a newly rendered image.
    with patch.object(ImageDraw.ImageDraw, "text", capture):
        render_card(data, "nfl", 0, rows=rows, now=AT.replace(minute=6))
    assert not any("Example Home ML" in text for text in labels)
    assert "No qualifying fresh research selections" in labels
    assert any("NOT OFFICIAL PICKS" in text for text in labels)


def test_compact_labels_keep_the_exact_market_side_threshold_player_and_period():
    assert compact_selection(modeled_row()) == "Example Home ML"
    assert compact_selection(modeled_row(market="spreads", line=1.5)) == "Example Home +1.5"
    assert (
        compact_selection(modeled_row(market="alternate_totals_h1", selection="Under", line=21.5))
        == "Under 21.5 · alt total · 1st half"
    )
    assert (
        compact_selection(
            modeled_row(
                market="player_receptions", participant="Test Player", selection="Over", line=5.5
            )
        )
        == "Test Player · Over 5.5 Receptions"
    )
    assert (
        compact_selection(
            modeled_row(
                market="player_anytime_td", participant="Test Player", selection="Yes", line=None
            )
        )
        == "Test Player · anytime TD"
    )
    assert (
        compact_selection(
            modeled_row(
                market="team_totals", participant="Example Home", selection="Over", line=24.5
            )
        )
        == "Example Home Over 24.5 · team total"
    )


def test_long_selection_names_wrap_without_losing_characters():
    from jabazi.sheet_images import wrapped, font
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 200)))
    name = "Unusually Long Player Name " + "X" * 160
    lines = wrapped(draw, name, font(36), 900)
    assert "".join("".join(lines).split()) == "".join(name.split())
    assert all(draw.textlength(line, font=font(36)) <= 900 for line in lines)

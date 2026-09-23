"""Deterministic research graphics: no generated data or synthetic percentages."""

import io
import math
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

from .discord_sheets import SPORTS

PAGE_SIZE = 24
SHEET_FORMAT_VERSION = 2
GROUPS = {
    "nfl": ("Game lines", "Player props", "Anytime touchdowns"),
    "mlb": ("Game lines", "Pitcher props", "Batter props"),
    "cfb": ("Moneylines & spreads", "Totals & team totals", "Period markets"),
}


def group_index(sport, market):
    market = market.lower()
    if sport == "nfl":
        if "anytime" in market and ("td" in market or "touchdown" in market):
            return 2
        return 1 if market.startswith("player_") else 0
    if sport == "mlb":
        return 1 if market.startswith("pitcher_") else 2 if market.startswith("batter_") else 0
    if any(period in market for period in ("_h1", "_h2", "_q1", "_q2", "_q3", "_q4")):
        return 2
    return 1 if "total" in market else 0


def grouped_rows(record, sport):
    if sport not in GROUPS:
        raise ValueError("Unknown sport")
    groups = [[], [], []]
    for row in record["payload"]["rows"]:
        if row["sport"] != SPORTS[sport]:
            continue
        if sport == "cfb" and row["market"].startswith(("player_", "pitcher_", "batter_")):
            continue
        groups[group_index(sport, row["market"])].append(row)
    for i, rows in enumerate(groups):
        unique = {}
        for row in rows:
            key = (
                event_key(row),
                row["market"],
                row.get("participant"),
                row["selection"],
                str(row.get("line")),
            )
            previous = unique.get(key)
            if previous is None or (
                str(row.get("price_time_utc", "")),
                float(row.get("decimal_odds") or 0),
            ) > (str(previous.get("price_time_utc", "")), float(previous.get("decimal_odds") or 0)):
                unique[key] = row
        rows = groups[i] = list(unique.values())
        rows.sort(
            key=lambda r: (r.get("starts_at_utc", ""), r["event"], r["market"], r["selection"])
        )
    return groups


def event_key(row):
    # IDs distinguish doubleheaders; legacy snapshots fall back to matchup + start.
    return row.get("event_id") or (row["event"], row.get("starts_at_utc", ""))


def slate_blocks(record, sport, group):
    """One matchup per game block; a representative standard threshold per market.

    Prices for different thresholds are never combined. Select the threshold
    observed across most books, then closest to balanced prices. No EV ranking.
    """
    rows = grouped_rows(record, sport)[group]
    buckets = {}
    if group == 0 or sport == "cfb":
        for event in record["payload"].get("slate_events", []):
            if event["sport"] == SPORTS[sport]:
                buckets[event_key(event)] = {**event, "rows": []}
    for row in rows:
        key = event_key(row)
        if row.get("participant"):
            key = (key, row["participant"], row["market"])
        block = buckets.setdefault(key, {**row, "rows": []})
        block["rows"].append(row)
    for block in buckets.values():
        markets = defaultdict(lambda: defaultdict(list))
        for row in block["rows"]:
            line = row.get("line")
            if line is not None:
                line = abs(float(line)) if "spread" in row["market"] else float(line)
            markets[(row["market"], row.get("participant"))][line].append(row)
        chosen = []
        for thresholds in markets.values():

            def rank(item):
                line, values = item
                return (
                    -sum(r.get("book_count", 0) for r in values),
                    sum(
                        abs(float(r.get("market_no_vig_probability") or 0.5) - 0.5) for r in values
                    ),
                    str(line),
                )

            chosen.extend(min(thresholds.items(), key=rank)[1])
        block["rows"] = chosen
    return sorted(
        buckets.values(),
        key=lambda b: (b.get("starts_at_utc") or "", b["event"], str(b.get("participant") or "")),
    )


def page_count(record, sport, group):
    return max(1, math.ceil(len(slate_blocks(record, sport, group)) / PAGE_SIZE))


def percentage(value):
    if value is None:
        return "Unavailable"
    try:
        number = float(value)
        return f"{number:.1%}" if math.isfinite(number) and 0 <= number <= 1 else "Unavailable"
    except (ValueError, TypeError):
        return "Unavailable"


def odds(value):
    try:
        decimal = float(value)
        if not math.isfinite(decimal) or decimal <= 1:
            return "--"
        american = (decimal - 1) * 100 if decimal >= 2 else -100 / (decimal - 1)
        return f"{american:+.0f}"
    except (ValueError, TypeError):
        return "--"


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size=size)


def short(draw, text, face, width):
    text = str(text or "--").replace("\n", " ")
    while draw.textlength(text, font=face) > width and len(text) > 1:
        text = text[:-2].rstrip() + "…"
    return text


def render_card(record, sport, group, *, page=1):
    if page < 1 or page > 1000 or group not in (0, 1, 2):
        raise ValueError("Invalid page or group")
    blocks = slate_blocks(record, sport, group)
    pages = max(1, math.ceil(len(blocks) / PAGE_SIZE))
    selected = blocks[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    healthy = record["payload"]["healthy"]
    if not healthy:
        selected = []
    layouts = []
    for block in selected:
        markets = defaultdict(list)
        for row in block["rows"]:
            markets[row["market"]].append(row)
        panels = list(markets.items()) or [("unavailable", [])]
        heights = []
        for offset in range(0, len(panels), 3):
            heights.append(46 + max(1, max(len(v) for _, v in panels[offset : offset + 3])) * 68)
        layouts.append((block, panels, heights, 80 + sum(heights)))
    height = 320 + (sum(x[3] for x in layouts) if layouts else 150)
    image = Image.new("RGB", (1400, height), "#100c1b")
    draw = ImageDraw.Draw(image)
    title, heading, body, small = font(38, True), font(24, True), font(21), font(18)
    draw.rectangle((0, 0, 1400, 9), fill="#ad68ff")
    draw.text((32, 24), "JABBAZI GURU", font=title, fill="#f9f5ff")
    draw.text((32, 76), f"{sport.upper()} / {GROUPS[sport][group]}", font=heading, fill="#c7a1ff")
    at = record["payload"]["completed_at"][:19].replace("T", " ")
    count_label = "matchups" if group == 0 or sport == "cfb" else "player markets"
    draw.text(
        (32, 115),
        f"Scan {at} UTC  |  {len(blocks)} {count_label}  |  Sheet {page}/{pages}",
        font=small,
        fill="#beb4cc",
    )
    notice = "PARTIAL SOURCE EXPORT" if record["payload"].get("truncated") else "RESEARCH ONLY"
    draw.text(
        (32, 146),
        f"{notice}  |  Model % is experimental; these are not official picks.",
        font=small,
        fill="#f4c674",
    )
    y = 190
    labels = {
        "h2h": "MONEYLINE",
        "spreads": "SPREAD",
        "totals": "TOTAL",
        "unavailable": "LINES UNAVAILABLE",
    }
    for block, panels, heights, block_height in layouts:
        draw.rounded_rectangle((20, y, 1380, y + block_height - 12), radius=12, fill="#20162e")
        name = block["event"]
        if block.get("participant"):
            name += " / " + block["participant"]
        draw.text((36, y + 10), short(draw, name, heading, 1000), font=heading, fill="white")
        start = str(block.get("starts_at_utc") or "")[:16].replace("T", " ")
        draw.text(
            (1090, y + 15),
            start + " UTC" if start else "Start unavailable",
            font=small,
            fill="#beb4cc",
        )
        panel_y = y + 50
        for offset in range(0, len(panels), 3):
            for column, (market, values) in enumerate(panels[offset : offset + 3]):
                x = 36 + column * 450
                draw.text(
                    (x, panel_y),
                    short(draw, labels.get(market, market.replace("_", " ").upper()), small, 424),
                    font=small,
                    fill="#c7a1ff",
                )
                if not values:
                    draw.text(
                        (x, panel_y + 30), "No fresh complete prices", font=body, fill="#b8aac8"
                    )
                for i, row in enumerate(sorted(values, key=lambda r: r["selection"])):
                    sy = panel_y + 28 + i * 68
                    line = "" if row.get("line") is None else str(row["line"])
                    selection = f"{row['selection']} {line}  {odds(row['decimal_odds'])}"
                    draw.text((x, sy), short(draw, selection, body, 424), font=body, fill="#f9f5ff")
                    model = (
                        percentage(row.get("research_probability"))
                        if row.get("model_version")
                        else "Unavailable"
                    )
                    detail = (
                        f"Model {model} / Market {percentage(row.get('market_no_vig_probability'))}"
                    )
                    draw.text(
                        (x, sy + 25), short(draw, detail, small, 424), font=small, fill="#c7a1ff"
                    )
                    price_at = str(row.get("price_time_utc", ""))[5:16].replace("T", " ")
                    draw.text(
                        (x, sy + 46),
                        short(draw, f"{row['book']} | {price_at} UTC", small, 424),
                        font=small,
                        fill="#b8aac8",
                    )
            panel_y += heights[offset // 3]
        y += block_height
    if not selected:
        message = (
            "DATA UNHEALTHY"
            if not healthy
            else "NO ROWS ON THIS PAGE"
            if blocks
            else "NOT AVAILABLE YET"
        )
        draw.text((36, 220), message, font=heading, fill="#f4c674")
        draw.text(
            (36, 270),
            "No prices or probabilities are invented to fill this category.",
            font=body,
            fill="#d5cbe1",
        )
    bottom = height - 105
    for i, line in enumerate(
        (
            "Feed slate coverage; games without usable odds stay visible. Prices are snapshots: recheck before betting.",
            "One representative threshold per market; Market % is no-vig pricing. Missing model % stays unavailable.",
            "All sheets are delivered automatically. No official picks or stakes are issued here.",
        )
    ):
        draw.text((32, bottom + i * 28), line, font=small, fill="#c6b8d7")
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()

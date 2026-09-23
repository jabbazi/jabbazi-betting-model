"""Deterministic research graphics: no generated data or synthetic percentages."""

import io
import math

from PIL import Image, ImageDraw, ImageFont

from .discord_sheets import SPORTS

PAGE_SIZE = 12
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
    for rows in groups:
        rows.sort(
            key=lambda r: (r.get("starts_at_utc", ""), r["event"], r["market"], r["selection"])
        )
    return groups


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
    rows = grouped_rows(record, sport)[group]
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    selected = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    healthy = record["payload"]["healthy"]
    if not healthy:
        selected = []
    height = 330 + max(1, len(selected)) * 128
    image = Image.new("RGB", (1200, height), "#100c1b")
    draw = ImageDraw.Draw(image)
    title, heading, body, small = font(42, True), font(27, True), font(23), font(18)
    draw.rectangle((0, 0, 1200, 10), fill="#ad68ff")
    draw.text((36, 30), "JABBAZI GURU", font=title, fill="#f9f5ff")
    draw.text((36, 88), f"{sport.upper()} / {GROUPS[sport][group]}", font=heading, fill="#c7a1ff")
    at = record["payload"]["completed_at"][:19].replace("T", " ")
    draw.text(
        (36, 132),
        f"Scan: {at} UTC  •  Page {page}/{pages}  •  {len(rows)} rows",
        font=small,
        fill="#beb4cc",
    )
    draw.text(
        (36, 163),
        "RESEARCH ONLY — NOT OFFICIAL PICKS • Prices are snapshots",
        font=small,
        fill="#f4c674",
    )
    draw.line((36, 204, 1164, 204), fill="#4c365f", width=2)
    for index, row in enumerate(selected):
        y = 220 + index * 128
        draw.rounded_rectangle((24, y - 5, 1176, y + 114), radius=12, fill="#20162e")
        draw.text((40, y), short(draw, row["event"], heading, 740), font=heading, fill="white")
        market = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}.get(
            row["market"], row["market"].replace("_", " ").title()
        )
        selection = f"{row['selection']} {row.get('line') if row.get('line') is not None else ''} • {market}"
        if row.get("participant"):
            selection = f"{row['participant']} • {selection}"
        draw.text((40, y + 35), short(draw, selection, body, 760), font=body, fill="#d5cbe1")
        model = (
            percentage(row.get("research_probability"))
            if row.get("model_version")
            else "Unavailable"
        )
        draw.text((825, y), "MODEL", font=small, fill="#b7a5ca")
        draw.text((825, y + 27), model, font=heading, fill="#c7a1ff")
        draw.text(
            (40, y + 72),
            short(
                draw,
                f"{row['book']} {odds(row['decimal_odds'])} • Market no-vig: {percentage(row.get('market_no_vig_probability'))}",
                small,
                745,
            ),
            font=small,
            fill="#b8aac8",
        )
        price_at = str(row.get("price_time_utc", ""))[5:16].replace("T", " ")
        draw.text((825, y + 70), f"Price {price_at} UTC", font=small, fill="#b8aac8")
        draw.text(
            (40, y + 95),
            short(draw, row.get("reason", "Research only"), small, 1100),
            font=small,
            fill="#f4c674",
        )
    if not selected:
        title_text = (
            "DATA UNHEALTHY"
            if not healthy
            else "NO ROWS ON THIS PAGE"
            if rows
            else "NOT AVAILABLE YET"
        )
        draw.text((40, 235), title_text, font=heading, fill="#f4c674")
        detail = "No probabilities or picks are invented to fill this sheet."
        draw.text((40, 280), detail, font=body, fill="#d5cbe1")
    bottom = height - 94
    draw.text(
        (36, bottom),
        "Market % reflects bookmaker pricing, not a validated model forecast.",
        font=small,
        fill="#c6b8d7",
    )
    draw.text(
        (36, bottom + 28),
        f"More rows: !cheatsheets {sport} <page> • Recheck price, start time and availability.",
        font=small,
        fill="#c6b8d7",
    )
    draw.text(
        (36, bottom + 56),
        "Missing model % means unavailable. No stake or BET recommendation is issued.",
        font=small,
        fill="#c6b8d7",
    )
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()

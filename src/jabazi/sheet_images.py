"""Deterministic research graphics: no generated data or synthetic percentages."""

import io
import math
from collections import defaultdict
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from .discord_sheets import SPORTS

PAGE_SIZE = 24
FEATURED_LIMIT = 12
SHEET_FORMAT_VERSION = 3
GROUPS = {
    "nfl": ("Game shortlist", "Player props", "Anytime touchdowns"),
    "mlb": ("Game shortlist", "Pitcher props", "Batter props"),
    "cfb": ("Game shortlist", "Team totals", "Period markets"),
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
    return 1 if "team_totals" in market else 0


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


def shortlist_rows(record, sport, group):
    """At most one research selection per game/player, across available markets.

    Rank supported predictions by conservative price value, not raw hit chance.
    This is an experimental comparison, never a betting approval. Missing models
    cannot gain a model percentage or edge from market prices.
    """
    grouped = grouped_rows(record, sport)[group]
    buckets = {}
    if group == 0 or sport == "cfb":
        for event in record["payload"].get("slate_events", []):
            if event["sport"] == SPORTS[sport]:
                buckets[event_key(event)] = {**event, "quotes": []}
    for row in grouped:
        key = event_key(row)
        if group != 0 and sport != "cfb":
            key = (key, row.get("participant"))
        block = buckets.setdefault(key, {**row, "quotes": []})
        block["quotes"].append(row)

    def fresh(row):
        try:
            at = datetime.fromisoformat(record["payload"]["completed_at"].replace("Z", "+00:00"))
            price = datetime.fromisoformat(row["price_time_utc"].replace("Z", "+00:00"))
            start = datetime.fromisoformat(row["starts_at_utc"].replace("Z", "+00:00"))
            return (
                0 <= (at - price).total_seconds() <= 120
                and start > at
                and not row.get("price_stale")
                and not row.get("in_play")
            )
        except (ValueError, TypeError, KeyError):
            return False

    result = []
    for block in buckets.values():
        eligible = []
        for row in block["quotes"]:
            try:
                p, q, u, d = (
                    float(row[k])
                    for k in (
                        "research_probability",
                        "market_no_vig_probability",
                        "uncertainty",
                        "decimal_odds",
                    )
                )
                if (
                    not all(math.isfinite(v) for v in (p, q, u, d))
                    or not 0 < p < 1
                    or not 0 < q < 1
                    or not 0 <= u < 1
                    or d <= 1
                    or not row.get("model_version")
                    or not fresh(row)
                    or not row.get("executable", row.get("book_count", 0) >= 2)
                ):
                    continue
                score = p * (1 - u) * d - 1
                eligible.append((score, p - q, row.get("book_count", 0), row))
            except (TypeError, ValueError, KeyError):
                continue
        chosen = (
            max(eligible, key=lambda x: (x[:3], x[3]["market"], str(x[3].get("line"))))
            if eligible
            else None
        )
        reference = None
        if chosen is None and group != 0 and sport != "cfb":
            # A neutral threshold reference for unmodeled player markets; never a pick.
            refs = [
                r for r in block["quotes"] if fresh(r) and r["selection"].lower() in {"over", "yes"}
            ]
            if refs:
                reference = max(
                    refs,
                    key=lambda r: (
                        r.get("book_count", 0),
                        -abs(float(r.get("market_no_vig_probability") or 0.5) - 0.5),
                        r["market"],
                        str(r.get("line")),
                    ),
                )
        result.append(
            {
                **block,
                "best": chosen[3] if chosen else None,
                "reference": reference,
                "edge": chosen[1] if chosen else None,
                "status": ("WATCH" if chosen[0] > 0 and chosen[1] > 0 else "PASS")
                if chosen
                else "NO MODEL",
            }
        )
    return sorted(
        result,
        key=lambda b: (b.get("starts_at_utc") or "", b["event"], str(b.get("participant") or "")),
    )



def featured_rows(record, sport, group, *, limit=FEATURED_LIMIT):
    """Return only positive, supported research edges for the member portal.

    Full-slate rows remain available to the owner/Discord sheet pipeline. The
    member app deliberately surfaces a short, ranked card and never promotes
    an unrated or negative-edge row into a pick-like view.
    """
    ranked = []
    for block in shortlist_rows(record, sport, group):
        best = block.get("best")
        edge = block.get("edge")
        if not best or block.get("status") != "WATCH" or edge is None:
            continue
        try:
            probability = float(best["research_probability"])
            uncertainty = float(best["uncertainty"])
            decimal = float(best["decimal_odds"])
            edge_value = float(edge)
            conservative_roi = probability * (1 - uncertainty) * decimal - 1
            if not all(math.isfinite(v) for v in (edge_value, conservative_roi)):
                continue
            if edge_value <= 0 or conservative_roi <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        ranked.append((conservative_roi, edge_value, int(best.get("book_count", 0) or 0), block))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[3] for item in ranked[:limit]]


def page_count(record, sport, group, *, rows=None):
    selected = shortlist_rows(record, sport, group) if rows is None else rows
    return max(1, math.ceil(len(selected) / PAGE_SIZE))


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


MARKET_LABELS = {
    "h2h": "ML",
    "spreads": "Spread",
    "alternate_spreads": "Alt spread",
    "totals": "Total",
    "alternate_totals": "Alt total",
    "team_totals": "Team total",
    "alternate_team_totals": "Alt team total",
    "player_pass_yds": "Pass yards",
    "player_reception_yds": "Rec yards",
    "player_rush_yds": "Rush yards",
    "player_receptions": "Receptions",
    "player_anytime_td": "Anytime TD",
    "player_pass_tds": "Pass TDs",
    "pitcher_strikeouts": "Strikeouts",
    "pitcher_outs": "Pitcher outs",
    "batter_hits": "Hits",
    "batter_total_bases": "Total bases",
    "batter_home_runs": "Home runs",
    "batter_rbis": "RBIs",
}


def selection_label(row, *, reference=False):
    market = MARKET_LABELS.get(row["market"], row["market"].replace("_", " "))
    line = "" if row.get("line") is None else f"{float(row['line']):g}"
    if "spread" in row["market"] and row.get("line") is not None:
        line = f"{float(row['line']):+g}"
    if reference:
        return f"{market} {line} · UNRATED".strip()
    side = row["selection"]
    if row["market"] == "h2h":
        return f"{side} ML"
    return f"{side} {line} · {market}".strip()


def render_card(record, sport, group, *, page=1, rows=None):
    if page < 1 or page > 1000 or group not in (0, 1, 2):
        raise ValueError("Invalid page or group")
    rows = shortlist_rows(record, sport, group) if rows is None else list(rows)
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    selected = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    healthy = record["payload"]["healthy"]
    if not healthy:
        selected = []
    height = 336 + max(2, len(selected)) * 64
    image = Image.new("RGB", (1400, height), "#100c1b")
    draw = ImageDraw.Draw(image)
    title, heading, body, small = font(35, True), font(23, True), font(20), font(17)
    draw.rectangle((0, 0, 1400, 8), fill="#ad68ff")
    draw.text((28, 22), "JABBAZI GURU", font=title, fill="#f9f5ff")
    draw.text((28, 70), f"{sport.upper()} / {GROUPS[sport][group]}", font=heading, fill="#c7a1ff")
    at = record["payload"]["completed_at"][:19].replace("T", " ")
    label = "games" if group == 0 or sport == "cfb" else "players"
    draw.text(
        (28, 110),
        f"{len(rows)} {label} · page {page}/{pages} · Snapshot {at} UTC",
        font=small,
        fill="#beb4cc",
    )
    notice = (
        "PARTIAL SOURCE EXPORT" if record["payload"].get("truncated") else "EXPERIMENTAL RESEARCH"
    )
    draw.text(
        (28, 140),
        f"{notice} · One selection per game/player when supported. No official picks.",
        font=small,
        fill="#f4c674",
    )
    draw.rectangle((20, 181, 1380, 218), fill="#322046")
    for x, text in [
        (30, "MATCHUP / PLAYER"),
        (493, "SELECTION / PRICE"),
        (966, "MODEL"),
        (1102, "MARKET"),
        (1235, "EDGE"),
    ]:
        draw.text((x, 187), text, font=small, fill="#d6b9ff")
    for index, item in enumerate(selected):
        y = 222 + index * 64
        if index % 2 == 0:
            draw.rectangle((20, y, 1380, y + 62), fill="#20162e")
        name = item.get("participant") if group != 0 and sport != "cfb" else item["event"]
        sub = (
            item["event"]
            if group != 0 and sport != "cfb"
            else str(item.get("starts_at_utc") or "")[:16].replace("T", " ") + " UTC"
        )
        # Two lines preserve both full team names at phone-readable type sizes.
        if group == 0 and " @ " in name:
            away, home = name.split(" @ ", 1)
            draw.text((30, y + 5), short(draw, away, body, 445), font=body, fill="white")
            draw.text((30, y + 31), short(draw, "@ " + home, body, 445), font=body, fill="#c4b8d0")
        else:
            draw.text((30, y + 5), short(draw, name, body, 445), font=body, fill="white")
            draw.text((30, y + 33), short(draw, sub, small, 445), font=small, fill="#b8aac8")
        chosen, reference = item["best"], item["reference"]
        if chosen:
            draw.text(
                (493, y + 5),
                short(draw, selection_label(chosen), body, 452),
                font=body,
                fill="#f9f5ff",
            )
            stamp = "PASS · " if item["status"] == "PASS" else ""
            detail = f"{stamp}{odds(chosen['decimal_odds'])} · {chosen['book']}"
            draw.text((493, y + 33), short(draw, detail, small, 452), font=small, fill="#b8aac8")
            model = percentage(chosen["research_probability"])
            market = percentage(chosen["market_no_vig_probability"])
            edge = f"{item['edge'] * 100:+.1f} pp"
        elif reference:
            draw.text(
                (493, y + 5),
                short(draw, selection_label(reference, reference=True), body, 452),
                font=body,
                fill="#c4b8d0",
            )
            draw.text(
                (493, y + 33), "No player model; market reference only", font=small, fill="#b8aac8"
            )
            model, market, edge = "—", percentage(reference["market_no_vig_probability"]), "—"
            market = ("O " if reference["selection"].lower() == "over" else "Y ") + market
        else:
            draw.text((493, y + 5), "NO SUPPORTED SELECTION", font=body, fill="#c4b8d0")
            draw.text(
                (493, y + 33),
                "Model or fresh comparable prices unavailable",
                font=small,
                fill="#b8aac8",
            )
            model = market = edge = "—"
        for x, value in ((966, model), (1102, market), (1235, edge)):
            draw.text((x, y + 15), value, font=body, fill="#ddd0f0")
    if not selected:
        text = (
            "DATA UNHEALTHY"
            if not healthy
            else "No supported player markets in this scan"
            if group
            else "No games returned in this scan"
        )
        draw.text((30, 250), text, font=heading, fill="#f4c674")
        draw.text(
            (30, 290),
            "Missing data never becomes a model percentage or a pick.",
            font=body,
            fill="#b8aac8",
        )
    draw.text(
        (28, height - 83),
        "Market = no-vig consensus. Edge = Model − Market in percentage points; not expected ROI.",
        font=small,
        fill="#beb4cc",
    )
    draw.text(
        (28, height - 56),
        "Compared by price value after uncertainty. Snapshots can move; recheck prices. Never a guarantee.",
        font=small,
        fill="#beb4cc",
    )
    draw.text(
        (28, height - 29),
        "No model = no model edge. Every feed matchup is kept, even when no selection is supported.",
        font=small,
        fill="#beb4cc",
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

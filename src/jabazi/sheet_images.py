"""Deterministic research graphics: no generated data or synthetic percentages."""

import io
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from .discord_sheets import SPORTS

PAGE_SIZE = 24
FEATURED_LIMIT = 12
PRICE_MAX_AGE_SECONDS = 120
SHEET_FORMAT_VERSION = 4
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


def price_valid_until(row):
    """Exclusive end of the pregame quote's freshness window (not a guarantee)."""
    price = datetime.fromisoformat(row["price_time_utc"].replace("Z", "+00:00"))
    start = datetime.fromisoformat(row["starts_at_utc"].replace("Z", "+00:00"))
    if price.tzinfo is None or start.tzinfo is None:
        raise ValueError("Aware quote and event times required")
    return min(start, price + timedelta(seconds=PRICE_MAX_AGE_SECONDS))


def shortlist_rows(record, sport, group, *, now=None):
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
                at.tzinfo is not None
                and price.tzinfo is not None
                and start.tzinfo is not None
                and 0 <= (at - price).total_seconds() < PRICE_MAX_AGE_SECONDS
                and start > at
                and (now is None or at <= now < price_valid_until(row))
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


def featured_rows(record, sport, group, *, limit=FEATURED_LIMIT, now=None):
    """Return only positive, supported research edges for the member portal.

    Full-slate rows remain available to the owner. The
    member app deliberately surfaces a short, ranked card and never promotes
    an unrated or negative-edge row into a pick-like view.
    """
    if type(limit) is not int or not 1 <= limit <= FEATURED_LIMIT:
        raise ValueError("Invalid featured limit")
    return supported_rows(record, sport, group, now=now)[:limit]


def supported_rows(record, sport, group, *, now=None):
    """All fresh positive research edges, one per event/player, without a top-N cap.

    Used by Discord's paginated lists. No neutral reference, negative edge or
    unavailable model is rendered as a selection. Owner archives are unchanged.
    """
    if not record or not record["payload"].get("healthy"):
        return []
    now = now or datetime.now(UTC)
    ranked = []
    for block in shortlist_rows(record, sport, group, now=now):
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
    return [item[3] for item in ranked]


def page_count(record, sport, group, *, rows=None, now=None):
    selected = supported_rows(record, sport, group, now=now) if rows is None else rows
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


def compact_selection(row):
    """A complete betting contract in plain language, not an internal market key."""
    market = row["market"]
    side = str(row["selection"])
    line = "" if row.get("line") is None else f"{float(row['line']):g}"
    period = next(
        (
            label
            for suffix, label in (
                ("_h1", "1st half"),
                ("_h2", "2nd half"),
                ("_q1", "1st quarter"),
                ("_q2", "2nd quarter"),
                ("_q3", "3rd quarter"),
                ("_q4", "4th quarter"),
            )
            if market.endswith(suffix)
        ),
        "",
    )
    base = market.rsplit("_", 1)[0] if period else market
    participant = str(row.get("participant") or "")
    if base == "h2h":
        label = f"{side} ML"
    elif base in {"spreads", "alternate_spreads"}:
        signed = f"{float(row['line']):+g}" if row.get("line") is not None else "line unavailable"
        label = f"{side} {signed}" + (" · alt spread" if base.startswith("alternate") else "")
    elif base in {"totals", "alternate_totals", "team_totals", "alternate_team_totals"}:
        team = f"{participant} " if "team_totals" in base and participant else ""
        kind = "team total" if "team_totals" in base else "total"
        kind = "alt " + kind if base.startswith("alternate") else kind
        label = f"{team}{side} {line} · {kind}"
    elif "anytime" in base and ("td" in base or "touchdown" in base):
        player = participant or side
        label = f"{player} · anytime TD" + (" · No" if side.lower() == "no" else "")
    else:
        kind = MARKET_LABELS.get(base, base.replace("_", " "))
        label = f"{participant} · {side} {line} {kind}" if participant else f"{side} {line} {kind}"
    return label.strip() + (f" · {period}" if period else "")


def wrapped(draw, text, face, width):
    """Wrap rather than truncate selection, player or matchup names."""
    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current}{word}".strip()
        if current and draw.textlength(candidate, font=face) > width:
            lines.append(current)
            current = ""
        # Provider labels can contain long unbroken words. Preserve every character.
        for char in word:
            candidate = current + char
            if draw.textlength(candidate, font=face) > width and current:
                lines.append(current.rstrip())
                current = char
            else:
                current = candidate
        current += " "
    if current.strip():
        lines.append(current.strip())
    return lines or ["—"]


def render_card(record, sport, group, *, page=1, rows=None, featured=False, now=None):
    """Mobile list image. Probabilities and detailed research stay in the app.

    Revalidate at render time, including rows supplied by the member endpoint.
    An archived research image never becomes an official card or a parlay.
    """
    if page < 1 or page > 1000 or group not in (0, 1, 2):
        raise ValueError("Invalid page or group")
    now = now or datetime.now(UTC)
    valid = supported_rows(record, sport, group, now=now)
    if rows is not None:
        # Intersect with current supported rows so an old app selection cannot
        # survive quote expiry while the image is being requested.
        valid = [item for item in rows if item in valid]
    pages = max(1, math.ceil(len(valid) / PAGE_SIZE))
    selected = valid[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    width, margin = 1080, 52
    image = Image.new("RGB", (width, 1), "#111113")
    draw = ImageDraw.Draw(image)
    brand, title, body, small = font(27, True), font(38, True), font(36), font(22)
    layout = []
    for item in selected:
        chosen = item["best"]
        lines = wrapped(draw, compact_selection(chosen), body, width - 2 * margin - 30)
        # Context distinguishes doubleheaders and identifies game totals unambiguously.
        context = item["event"]
        try:
            start = datetime.fromisoformat(chosen["starts_at_utc"].replace("Z", "+00:00"))
            context += " · " + start.astimezone(ZoneInfo("America/Chicago")).strftime(
                "%-I:%M %p %Z"
            )
        except (ValueError, KeyError, TypeError):
            pass
        sublines = wrapped(draw, context, small, width - 2 * margin - 30)
        layout.append((lines, sublines, 46 * len(lines) + 29 * len(sublines) + 24))
    height = 325 + sum(item[2] for item in layout) if layout else 480
    image = Image.new("RGB", (width, height), "#111113")
    draw = ImageDraw.Draw(image)
    draw.rectangle((margin, 38, margin + 5, 66), fill="#b78aff")
    draw.text((margin + 20, 35), "JABBAZI GURU", font=brand, fill="#c4a1ff")
    title_text = (
        f"{sport.upper()} CHEAT SHEET"
        if group == 0
        else f"{sport.upper()} {GROUPS[sport][group].upper()}"
    )
    draw.text((margin, 88), title_text, font=title, fill="#f5f5f6")
    try:
        at = datetime.fromisoformat(record["payload"]["completed_at"].replace("Z", "+00:00"))
        date = at.astimezone(ZoneInfo("America/Chicago")).strftime("%A · %b %-d · %-I:%M %p %Z")
    except (ValueError, KeyError, TypeError):
        date = "Snapshot time unavailable"
    draw.text((margin, 145), date, font=small, fill="#a3a3ad")
    notice = "RESEARCH ONLY · NOT OFFICIAL PICKS"
    if record["payload"].get("truncated"):
        notice += " · PARTIAL SLATE"
    draw.text((margin, 180), notice, font=font(19, True), fill="#d7bd88")
    y = 242
    for lines, sublines, row_height in layout:
        draw.ellipse((margin, y + 18, margin + 9, y + 27), fill="#e9e9ed")
        for i, line in enumerate(lines):
            draw.text((margin + 29, y + i * 46), line, font=body, fill="#f5f5f6")
        for i, line in enumerate(sublines):
            draw.text((margin + 29, y + len(lines) * 46 + i * 29), line, font=small, fill="#9e9ea8")
        y += row_height
    if not layout:
        message = (
            "Data unavailable"
            if not record["payload"]["healthy"]
            else "No qualifying fresh research selections"
        )
        draw.text((margin, 253), message, font=font(30, True), fill="#e9e9ed")
        draw.text(
            (margin, 310),
            "Updated selections appear when supported data is available.",
            font=small,
            fill="#a3a3ad",
        )
    draw.line((margin, height - 66, width - margin, height - 66), fill="#35353b")
    draw.text(
        (margin, height - 48),
        "Snapshot only · Recheck prices in the app",
        font=small,
        fill="#a3a3ad",
    )
    page_label = f"{page}/{pages}"
    draw.text(
        (width - margin - draw.textlength(page_label, font=small), height - 48),
        page_label,
        font=small,
        fill="#a3a3ad",
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

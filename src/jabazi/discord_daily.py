"""Date-scoped JABBAZI daily game winner sheets.

The scheduled sheet is intentionally different from the Main Card:
- one verified pregame event on the requested Central-time date = one game card;
- every card has a researched projected winner when sufficient evidence exists;
- a projected winner is never promoted into an official wager by this module.
"""
from __future__ import annotations

import io
import math
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .persistence.store import digest

MONEYLINE_MARKET = "h2h"
FORMAT_VERSION = 4
DEFAULT_DAILY_SPORTS = ("NFL", "CFB", "NBA", "WNBA", "MLB", "NHL")
VALID_STATUSES = {"BET NOW", "WATCH", "PASS", "PRICE CHECK", "UNAVAILABLE", "QUARANTINED"}
HOT_PINK = "#FF0A8A"
NEON_PINK = "#FF1493"
MAGENTA = "#D90068"
BLACK = "#090909"
CHARCOAL = "#121212"
GRAPHITE = "#1A1A1F"
SILVER = "#D9D9D9"
WHITE = "#FFFFFF"


def sport_label(sport):
    from .catalog import SPORTS
    for label, patterns in SPORTS.items():
        if any(
            sport == pattern
            or (pattern.endswith("*") and sport.startswith(pattern[:-1]))
            for pattern in patterns
        ):
            return "CFB" if label == "NCAAF" else label
    return None


def configured_daily_sports():
    raw = os.getenv("JABBAZI_DAILY_SPORTS", ",".join(DEFAULT_DAILY_SPORTS))
    allowed = tuple(dict.fromkeys(x.strip().upper() for x in raw.split(",") if x.strip()))
    return allowed or DEFAULT_DAILY_SPORTS


def _aware(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _on_local_date(value, date, timezone):
    stamp = _aware(value)
    return bool(stamp and stamp.astimezone(ZoneInfo(timezone)).date().isoformat() == date)


def _normalize_status(value, row, *, projection_source):
    status = str(value or "WATCH").replace("_", " ").upper()
    if status not in VALID_STATUSES:
        status = "WATCH"
    if row.get("price_stale") or row.get("executable") is not True:
        return "PRICE CHECK" if status != "QUARANTINED" else status
    if status == "BET NOW" and (
        projection_source != "MODEL"
        or row.get("model_can_influence_cash") is not True
    ):
        return "WATCH"
    return status


def _confidence(probability, *, source, agreement=True):
    p = probability if probability is not None else 0.5
    if source == "MODEL":
        if p >= 0.62 and agreement:
            return "A — Strong Projection"
        if p >= 0.57:
            return "B — Solid Lean"
        if p >= 0.53:
            return "C — Slight Lean"
        return "D — Near Coin Flip"
    if p >= 0.62:
        return "B — Solid Lean"
    if p >= 0.55:
        return "C — Slight Lean"
    return "D — Near Coin Flip"


def _best_market_row(rows):
    candidates = [
        row for row in rows
        if row.get("executable") is True
        and not row.get("price_stale")
        and (_number(row.get("market_no_vig_probability")) or 0) > 0
    ]
    return max(
        candidates,
        key=lambda row: (
            _number(row.get("market_no_vig_probability")) or 0,
            int(row.get("book_count") or 0),
            _number(row.get("decimal_odds")) or 0,
        ),
        default=None,
    )


def _best_model_row(rows):
    candidates = [
        row for row in rows
        if row.get("model_version")
        and row.get("data_health") == "HEALTHY"
        and row.get("model_stage") in {"SHADOW_ONLY", "LIMITED_LIVE", "PRODUCTION_APPROVED"}
        and row.get("status") != "QUARANTINED"
        and row.get("anomaly_state") != "QUARANTINED"
        and 0 < (_number(row.get("model_probability")) or 0) < 1
    ]
    return max(
        candidates,
        key=lambda row: (
            _number(row.get("model_probability")) or 0,
            -(_number(row.get("uncertainty")) or 0),
            int(row.get("book_count") or 0),
        ),
        default=None,
    )


def _projection(event, rows):
    model = _best_model_row(rows)
    market = _best_market_row(rows)
    if model is not None and (_number(model.get("model_probability")) or 0) >= 0.5:
        chosen, source = model, "MODEL"
        probability = _number(model.get("model_probability"))
    elif market is not None and (_number(market.get("market_no_vig_probability")) or 0) >= 0.5:
        chosen, source = market, "MARKET CONSENSUS"
        probability = _number(market.get("market_no_vig_probability"))
    else:
        chosen = source = probability = None

    if chosen is None:
        return {
            **event,
            "projected_winner": "UNAVAILABLE — insufficient verified data",
            "projection_source": "UNAVAILABLE",
            "confidence": "—",
            "model_probability": None,
            "model_version": None,
            "market_no_vig_probability": None,
            "book": None,
            "decimal_odds": None,
            "status": "PASS",
            "why": ["No fresh comparable moneyline evidence was available."],
            "risk": ["No winner was guessed or fabricated."],
            "data_health": "UNAVAILABLE",
        }

    market_favorite = market.get("selection") if market else None
    agreement = market_favorite in {None, chosen.get("selection")}
    chosen_market = _number(chosen.get("market_no_vig_probability"))
    why = []
    if source == "MODEL":
        why.append("Independent JABBAZI model favors this side.")
        if market and agreement:
            why.append("Model and no-vig market favorite agree.")
        elif market and not agreement:
            why.append("Model disagrees with the current market favorite.")
    else:
        why.append("Independent production model probability is unavailable.")
        why.append("Projected winner follows current no-vig market consensus.")
    reason = str(chosen.get("reason") or "").strip()
    if reason and reason.lower() not in {"market only", "test"}:
        why.append(reason[:180])

    risk = []
    uncertainty = _number(chosen.get("uncertainty"))
    if source != "MODEL":
        risk.append("Market-based projection; no independent model probability.")
    if not agreement:
        risk.append("Model/market disagreement increases uncertainty.")
    if probability is not None and probability < 0.55:
        risk.append("Small separation from a coin flip.")
    if uncertainty is not None and uncertainty >= 0.10:
        risk.append("Model uncertainty is elevated.")
    if not risk:
        risk.append("Single-game variance remains material.")

    return {
        **event,
        "projected_winner": str(chosen.get("selection") or "UNAVAILABLE"),
        "projection_source": source,
        "confidence": _confidence(probability, source=source, agreement=agreement),
        "model_probability": _number(chosen.get("model_probability")) if source == "MODEL" else None,
        "model_version": chosen.get("model_version") if source == "MODEL" else None,
        "model_stage": chosen.get("model_stage", "UNAVAILABLE") if source == "MODEL" else "UNAVAILABLE",
        "market_no_vig_probability": chosen_market,
        "book": chosen.get("book"),
        "decimal_odds": _number(chosen.get("decimal_odds")),
        "status": _normalize_status(chosen.get("status"), chosen, projection_source=source),
        "why": why[:5],
        "risk": risk[:5],
        "data_health": chosen.get("data_health", "UNKNOWN"),
        "price_time_utc": chosen.get("price_time_utc"),
        "edge": _number(chosen.get("edge")),
    }


def freeze_daily_moneyline(store, research_sheet, *, now=None, timezone="America/Chicago"):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Aware freeze time required")
    local = now.astimezone(ZoneInfo(timezone))
    date = local.date().isoformat()
    existing = store.list_records("daily_moneyline_sheet", 10, entity=date)
    current = next((row for row in existing if row.get("payload", {}).get("format_version") == FORMAT_VERSION), None)
    if current:
        return current["id"], False

    payload = research_sheet["payload"]
    if not payload.get("healthy") or payload.get("truncated"):
        raise ValueError("Cannot freeze an unhealthy research sheet")
    completed = _aware(payload.get("completed_at"))
    if completed is None or not 0 <= (now - completed).total_seconds() <= 900:
        raise ValueError("A fresh dedicated scan is required for the daily freeze")

    allowed = set(configured_daily_sports())
    events = {}
    for event in payload.get("slate_events", []):
        label = sport_label(event.get("sport"))
        if label not in allowed or not _on_local_date(event.get("starts_at_utc"), date, timezone):
            continue
        start = _aware(event.get("starts_at_utc"))
        if start is None or start <= now:
            continue
        key = (event.get("sport"), str(event.get("event_id") or ""))
        if not key[1]:
            continue
        events[key] = {
            "sport": event.get("sport"),
            "sport_label": label,
            "event_id": key[1],
            "event": event.get("event") or key[1],
            "starts_at_utc": event.get("starts_at_utc"),
        }

    rows_by_event = {key: [] for key in events}
    for row in payload.get("rows", []):
        if row.get("market") != MONEYLINE_MARKET:
            continue
        key = (row.get("sport"), str(row.get("event_id") or ""))
        if key not in events or not _on_local_date(row.get("starts_at_utc"), date, timezone):
            continue
        rows_by_event[key].append({
            **row,
            "model_probability": row.get("research_probability"),
            "edge": row.get("probability_edge"),
        })

    cards = [_projection(events[key], rows_by_event.get(key, [])) for key in sorted(
        events,
        key=lambda k: (_aware(events[k]["starts_at_utc"]) or now, events[k]["sport_label"], events[k]["event"]),
    )]

    if len(cards) != len(events):
        raise RuntimeError("Daily slate count verification failed")
    if any(not _on_local_date(card.get("starts_at_utc"), date, timezone) for card in cards):
        raise RuntimeError("Out-of-date game leaked into daily sheet")

    frozen = {
        "format_version": FORMAT_VERSION,
        "date": date,
        "timezone": timezone,
        "generated_at": now.isoformat(),
        "source_research_sheet_id": research_sheet["id"],
        "source_scan_completed_at": payload.get("completed_at"),
        "data_freshness": "snapshot",
        "sports": sorted(allowed),
        "notice": "Projected winner is research, not automatically an official JABBAZI wager.",
        "rows": cards,
        "row_count": len(cards),
        "eligible_game_count": len(events),
        "verified_count_match": len(cards) == len(events),
    }
    key = digest(["daily_moneyline_sheet", date, FORMAT_VERSION, frozen])
    if not store.append("daily_moneyline_sheet", date, frozen, key):
        return key, False
    return key, True


def daily_moneyline(store, *, now=None, timezone="America/Chicago"):
    now = now or datetime.now(UTC)
    date = now.astimezone(ZoneInfo(timezone)).date().isoformat()
    rows = store.list_records("daily_moneyline_sheet", 20, entity=date)
    return next((row for row in rows if row.get("payload", {}).get("format_version") == FORMAT_VERSION), None)


def _odds(value):
    if value is None:
        return "—"
    return f"{(value - 1) * 100:+.0f}" if value >= 2 else f"{-100 / (value - 1):+.0f}"


def _pct(value):
    return "Unavailable" if value is None else f"{value:.1%}"


def render_text(record):
    if record is None:
        return "Today's JABBAZI game cheat sheets are not available yet."
    p = record["payload"]
    lines = [
        "🔥 **JABBAZI — DAILY WINNER BOARD**",
        f"**{p['date']} • America/Chicago**",
        f"{p['row_count']} eligible games • {p['row_count']} game cards",
        "",
    ]
    if not p["rows"]:
        lines.append("No eligible primary-league games remain on today's verified pregame slate.")
    for row in p["rows"]:
        start = _aware(row.get("starts_at_utc"))
        time_text = start.astimezone(ZoneInfo(p["timezone"])).strftime("%I:%M %p CT") if start else "Time unavailable"
        lines.extend([
            f"**{row['sport_label']} • {row.get('event')} • {time_text}**",
            f"Projected Winner: **{row.get('projected_winner')}**",
            f"Confidence: {row.get('confidence')} • Betting status: **{row.get('status')}**",
            "",
        ])
    lines.append("Projected winner ≠ official bet. Official wagers appear only in Main Card.")
    return "\n".join(lines)[:1900]


def _font(size, bold=False):
    from PIL import ImageFont
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _wrapped(draw, text, face, width):
    words = str(text or "").split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=face) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ["—"]


def render_game_card(record, row):
    from PIL import Image, ImageDraw
    p = record["payload"]
    image = Image.new("RGB", (1200, 900), BLACK)
    draw = ImageDraw.Draw(image)

    from .vip.graphics import approved_logo_path, text_fit
    from PIL import ImageOps
    with Image.open(approved_logo_path()) as original:
        logo = ImageOps.contain(original.convert("RGBA"), (320, 205))
    image.paste(logo, (45, 25), logo)
    draw.text((405, 75), "DAILY GAME RESEARCH", font=_font(38, True), fill=WHITE)
    draw.text((405, 135), str(p["date"]) + " • America/Chicago", font=_font(23), fill=HOT_PINK)
    generated = _aware(p.get("generated_at"))
    stamp = generated.astimezone(ZoneInfo("America/Chicago")).strftime("%I:%M %p CT") if generated else "Unavailable"
    draw.text((405, 177), "Snapshot: " + stamp, font=_font(19), fill=SILVER)

    draw.rectangle((0, 0, 1200, 8), fill=HOT_PINK)
    draw.rectangle((36, 255, 1164, 865), outline=HOT_PINK, width=3)
    heading = _font(28, True)
    body = _font(23)
    small = _font(19)

    start = _aware(row.get("starts_at_utc"))
    time_text = start.astimezone(ZoneInfo(p["timezone"])).strftime("%b %d • %I:%M %p CT") if start else "Time unavailable"
    draw.text((58, 278), f"{row['sport_label']} • {time_text}", font=small, fill=HOT_PINK)
    text_fit(draw, (58, 316), row.get("event") or row.get("event_id"), max_width=1080, size=34, bold=True)

    draw.rectangle((58, 380, 1140, 495), fill=GRAPHITE, outline=NEON_PINK, width=2)
    draw.text((82, 397), "PROJECTED WINNER", font=small, fill=SILVER)
    winner = str(row.get("projected_winner") or "UNAVAILABLE")
    text_fit(draw, (82, 430), winner, max_width=1030, size=42, bold=True)

    draw.text((58, 525), "CONFIDENCE", font=small, fill=HOT_PINK)
    draw.text((58, 555), str(row.get("confidence") or "—"), font=heading, fill=WHITE)
    draw.text((625, 525), "BETTING STATUS", font=small, fill=HOT_PINK)
    draw.text((625, 555), str(row.get("status") or "PASS"), font=heading, fill=WHITE)

    model = _pct(row.get("model_probability"))
    market = _pct(row.get("market_no_vig_probability"))
    price = (str(row.get("book")) + " " + _odds(row.get("decimal_odds"))) if row.get("book") else "Unavailable"
    draw.text((58, 610), f"JABBAZI MODEL: {model}", font=body, fill=SILVER)
    draw.text((58, 646), f"MARKET NO-VIG: {market}", font=body, fill=SILVER)
    text_fit(draw, (58, 682), f"BEST OBSERVED PRICE: {price}", max_width=530, size=23, fill=SILVER)
    text_fit(draw, (58, 718), f"SOURCE: {row.get('projection_source')}", max_width=530, size=23, fill=SILVER)
    text_fit(draw, (58, 756), f"MODEL: {row.get('model_stage') or 'UNAVAILABLE'}", max_width=530, size=19, fill=SILVER)

    draw.text((625, 610), "WHY", font=small, fill=HOT_PINK)
    y = 642
    for item in row.get("why", [])[:3]:
        for line in _wrapped(draw, "• " + item, small, 500):
            draw.text((625, y), line, font=small, fill=WHITE)
            y += 27
            if y > 735:
                break
        if y > 735:
            break

    draw.text((625, 755), "RISK", font=small, fill=HOT_PINK)
    y = 787
    for item in row.get("risk", [])[:2]:
        for line in _wrapped(draw, "• " + item, small, 500):
            draw.text((625, y), line, font=small, fill=SILVER)
            y += 26
            if y > 845:
                break
        if y > 845:
            break

    draw.rectangle((36, 857, 1164, 897), fill=BLACK)
    text_fit(draw, (58, 864), "RESEARCH ONLY • Projected winner is not an official wager.", max_width=1080, size=19, fill=SILVER)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

"""Immutable once-daily Discord moneyline sheet."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .persistence.store import digest

MONEYLINE_MARKET="h2h"
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



def freeze_daily_moneyline(store, research_sheet, *, now=None, timezone="America/Chicago"):
    now=now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Aware freeze time required")
    local=now.astimezone(ZoneInfo(timezone))
    date=local.date().isoformat()
    existing=store.list_records("daily_moneyline_sheet",1,entity=date)
    if existing:
        return existing[0]["id"],False
    payload=research_sheet["payload"]
    if not payload.get("healthy"):
        raise ValueError("Cannot freeze an unhealthy research sheet")
    rows=[]
    for row in payload.get("rows",[]):
        if row.get("market")!=MONEYLINE_MARKET:
            continue
        label=sport_label(row.get("sport"))
        if label is None:
            continue
        rows.append({
            "sport":row["sport"],
            "sport_label":label,
            "event_id":row.get("event_id"),
            "event":row.get("event"),
            "selection":row.get("selection"),
            "book":row.get("book"),
            "decimal_odds":row.get("decimal_odds"),
            "price_time_utc":row.get("price_time_utc"),
            "starts_at_utc":row.get("starts_at_utc"),
            "market_no_vig_probability":row.get("market_no_vig_probability"),
            "model_probability":row.get("research_probability"),
            "model_version":row.get("model_version"),
            "uncertainty":row.get("uncertainty"),
            "edge":row.get("probability_edge"),
            "status":row.get("status"),
            "data_health":row.get("data_health","UNKNOWN"),
            "reason":row.get("reason"),
            "price_stale":row.get("price_stale"),
            "executable":row.get("executable"),
        })
    frozen={
        "date":date,
        "timezone":timezone,
        "generated_at":now.isoformat(),
        "source_research_sheet_id":research_sheet["id"],
        "source_scan_completed_at":payload.get("completed_at"),
        "data_freshness":"snapshot",
        "unit_reference":"1u = $30 unless the published unit reference changes",
        "notice":"A model lean is not automatically an official JABBAZI wager.",
        "rows":rows,
        "row_count":len(rows),
    }
    key=digest(["daily_moneyline_sheet",date])
    if not store.append("daily_moneyline_sheet",date,frozen,key):
        return key,False
    return key,True


def daily_moneyline(store, *, now=None, timezone="America/Chicago"):
    now=now or datetime.now(UTC)
    date=now.astimezone(ZoneInfo(timezone)).date().isoformat()
    rows=store.list_records("daily_moneyline_sheet",1,entity=date)
    return rows[0] if rows else None


def render_text(record):
    if record is None:
        return "Today's JABBAZI moneyline cheat sheet is not available yet."
    p=record["payload"]
    lines=[
        "🟣 **JABBAZI GURU — DAILY MONEYLINE CHEAT SHEET**",
        f"**{p['date']} • Generated {p['generated_at']}**",
        f"Data: {p['data_freshness']} • {p['unit_reference']}",
        "",
    ]
    if not p["rows"]:
        lines.append("No supported moneyline markets qualified for today's frozen sheet.")
    for row in p["rows"]:
        model=row.get("model_probability")
        market=row.get("market_no_vig_probability")
        edge=row.get("edge")
        def pct(v):
            return "—" if v is None else f"{float(v):.1%}"
        price="—"
        if row.get("decimal_odds") is not None:
            d=float(row["decimal_odds"])
            american=(d-1)*100 if d>=2 else -100/(d-1)
            price=f"{row.get('book') or 'book'} {american:+.0f}"
        status=row.get("status") or "WATCH"
        lines.extend([
            f"**{row['sport_label']} • {row.get('event') or row.get('event_id')}**",
            f"{row.get('selection')} • {price}",
            f"Model {pct(model)} | Market {pct(market)} | Edge {pct(edge)} | "
            f"Data {row.get('data_health','UNKNOWN')} | {status}",
            "",
        ])
    lines.append(p["notice"])
    return "\n".join(lines)[:3900]

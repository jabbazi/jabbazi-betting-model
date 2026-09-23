"""Auditable research sheets; never an official pick publisher."""

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal

from .persistence.store import digest

SPORTS = {"mlb": "baseball_mlb", "nfl": "americanfootball_nfl", "cfb": "americanfootball_ncaaf"}
MAX_ROWS = 10000
COLUMNS = (
    "sport",
    "event",
    "market",
    "selection",
    "line",
    "book",
    "decimal_odds",
    "price_time_utc",
    "starts_at_utc",
    "market_no_vig_probability",
    "research_probability",
    "model_version",
    "uncertainty",
    "probability_edge",
    "expected_roi",
    "status",
    "reason",
)


def iso(value):
    return value.isoformat() if value is not None else ""


def archive_sheets(store, result, *, now=None):
    """One immutable snapshot for exactly this scan, including empty/failed scans."""
    now = now or datetime.now(UTC)
    rows = []
    for action in result.actions[:MAX_ROWS]:
        c = action.price
        if c.sport not in SPORTS.values():
            continue
        # The LA-facing sheet never includes college player markets.
        if c.sport == SPORTS["cfb"] and (
            c.participant or c.market.startswith(("player_", "pitcher_", "batter_"))
        ):
            continue
        rows.append(
            dict(
                zip(
                    COLUMNS,
                    (
                        c.sport,
                        c.event,
                        c.market,
                        c.selection,
                        c.line,
                        c.best_book,
                        c.best_decimal,
                        iso(c.source_timestamp),
                        iso(c.starts_at),
                        c.consensus_probability,
                        action.model_probability,
                        action.model_version,
                        action.uncertainty,
                        action.probability_edge,
                        action.expected_roi,
                        "DATA_UNHEALTHY" if result.errors else "RESEARCH / NOT AN OFFICIAL PICK",
                        action.reason,
                    ),
                    strict=True,
                )
            )
        )
        rows[-1]["participant"] = c.participant
        rows[-1]["event_id"] = getattr(c, "event_id", "")
        rows[-1]["book_count"] = len(getattr(c, "book_prices", {}))
    payload = {
        "completed_at": now.isoformat(),
        "healthy": not result.errors,
        "error_count": len(result.errors),
        "feeds": result.feeds_scanned,
        "quotes": result.quotes_archived,
        "rows": rows,
        "slate_events": [
            e for e in getattr(result, "slate_events", ()) if e["sport"] in SPORTS.values()
        ],
        "coverage": "All events returned by scanned odds feeds; not an independently verified league schedule",
        "truncated": len(result.actions) > MAX_ROWS,
        "notice": "Research only. Prices are historical snapshots; recheck before acting. "
        "No official picks or stakes are issued by this sheet.",
    }
    key = digest(["research_sheet", payload])
    store.append("research_sheet", "latest_scan", payload, key)
    return key


def latest_sheet(store, *, now=None, max_age_seconds=10800):
    now = now or datetime.now(UTC)
    records = store.list_records("research_sheet", 1, entity="latest_scan")
    if not records:
        return None
    record = records[0]
    p = record["payload"]
    at = datetime.fromisoformat(p["completed_at"])
    if at.tzinfo is None or not 0 <= (now - at).total_seconds() <= max_age_seconds:
        return None
    return record


def safe_cell(value):
    if value is None:
        return ""
    text = str(value)
    # Prevent spreadsheet formula injection from provider-controlled labels.
    if not isinstance(value, (int, float, Decimal)) and text.lstrip().startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ):
        text = "'" + text
    return text


def sheet_csv(record, sport):
    if sport not in SPORTS:
        raise ValueError("Use mlb, nfl, or cfb")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for row in record["payload"]["rows"]:
        if row["sport"] == SPORTS[sport]:
            writer.writerow([safe_cell(row.get(c)) for c in COLUMNS])
    return output.getvalue().encode("utf-8-sig")


def scanner_status(store, *, now=None):
    now = now or datetime.now(UTC)
    records = store.list_records("worker_heartbeat", 1, entity="research_worker")
    state, at = "UNAVAILABLE", "No worker heartbeat"
    if records:
        p = records[0]["payload"]
        at = p.get("completed_at", "")
        try:
            timestamp = datetime.fromisoformat(at)
            age = (now - timestamp).total_seconds()
            state = p.get("status", "UNAVAILABLE") if 0 <= age <= 180 else "STALE"
        except (ValueError, TypeError):
            state = "UNAVAILABLE"
    return (
        f"JABBAZI Research — {state}\nLast worker heartbeat (UTC): {at}\n"
        "Research mode. Automated official picks are not enabled. "
        "!vip reports status; it does not grant membership or trigger a paid scan."
    )


def parse_command(content):
    parts = content.strip().lower().split()
    if parts == ["!vip"]:
        return "status", ()
    if parts == ["!cheatsheets"]:
        return "sheets", tuple(SPORTS)
    if len(parts) == 2 and parts[0] == "!cheatsheets" and parts[1] in SPORTS:
        return "sheets", (parts[1],)
    if len(parts) == 3 and parts[0] == "!cheatsheets" and parts[1] in SPORTS:
        if parts[2].isdigit() and 1 <= int(parts[2]) <= 1000:
            return "sheets", (parts[1],), int(parts[2])
    return None

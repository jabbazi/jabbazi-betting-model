"""Auditable research sheets; never an official pick publisher."""

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal

from .persistence.store import digest
from .catalog import SPORTS as CATALOG_SPORTS

SPORTS = {
    "mlb": "baseball_mlb",
    "nfl": "americanfootball_nfl",
    "cfb": "americanfootball_ncaaf",
}
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
        if not any(
            c.sport == pattern
            or (pattern.endswith("*") and c.sport.startswith(pattern[:-1]))
            for patterns in CATALOG_SPORTS.values()
            for pattern in patterns
        ):
            continue
        # The LA-facing sheet never includes college player markets.
        if c.sport == SPORTS["cfb"] and (
            c.market.startswith(("player_", "pitcher_", "batter_"))
            or (c.participant and c.market not in {"team_totals", "alternate_team_totals"})
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
                        "DATA_UNHEALTHY"
                        if result.errors
                        else (
                            str(action.decision.value).replace("_", " ")
                            if getattr(action, "decision", None) is not None
                            else "RESEARCH / NOT AN OFFICIAL PICK"
                        ),
                        action.reason,
                    ),
                    strict=True,
                )
            )
        )
        rows[-1]["participant"] = c.participant
        rows[-1]["event_id"] = getattr(c, "event_id", "")
        rows[-1]["book_count"] = len(getattr(c, "book_prices", {}))
        rows[-1]["executable"] = c.executable
        rows[-1]["price_stale"] = c.stale
        rows[-1]["in_play"] = c.in_play
        reliability = getattr(action, "reliability", None) or {}
        health_value = (reliability.get("research_priority_components") or {}).get(
            "data_health"
        )
        rows[-1]["data_health"] = (
            "HEALTHY"
            if health_value == 1 and not c.stale and not c.in_play
            else "UNHEALTHY"
            if health_value == 0
            else "UNKNOWN"
        )
    payload = {
        "completed_at": now.isoformat(),
        "healthy": not result.errors,
        "error_count": len(result.errors),
        "feeds": result.feeds_scanned,
        "event_market_coverage": getattr(result, "event_market_coverage", None),
        "quotes": result.quotes_archived,
        "rows": rows,
        "slate_events": [
            e
            for e in getattr(result, "slate_events", ())
            if any(
                e["sport"] == pattern
                or (pattern.endswith("*") and e["sport"].startswith(pattern[:-1]))
                for patterns in CATALOG_SPORTS.values()
                for pattern in patterns
            )
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
    try:
        at = datetime.fromisoformat(p["completed_at"])
        if at.tzinfo is None or not 0 <= (now - at).total_seconds() <= max_age_seconds:
            return None
    except (ValueError, TypeError, KeyError):
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
    lines = [f"JABBAZI GURU — {state}", f"Worker heartbeat (UTC): {at}"]
    from .models.registry import load_models
    from .models.player_registry import load_player_models, player_status
    models, errors = load_models(store)
    players, player_errors = load_player_models(store)
    for label, sport in (("NFL", "americanfootball_nfl"), ("MLB", "baseball_mlb"),
                        ("CFB", "americanfootball_ncaaf"), ("NBA", "basketball_nba"), ("NHL", "icehockey_nhl")):
        model = models.get(sport)
        artifact = model.artifact if model else {}
        stage = artifact.get("stage") or artifact.get("status") or "UNAVAILABLE"
        pstage = player_status(players, sport)["status"]
        lines.append(f"{label}: {stage} • Players: {pstage}")
    sheets = store.list_records("research_sheet", 100, entity="latest_scan")
    healthy = next((r["payload"].get("completed_at") for r in sheets if r["payload"].get("healthy")), None)
    lines.append(f"Last healthy scan (UTC): {healthy or 'UNAVAILABLE'}")
    provider = "UNAVAILABLE" if not sheets else "HEALTHY" if sheets[0]["payload"].get("healthy") else "UNHEALTHY"
    lines.append(f"Latest provider scan: {provider} • Model load failures: {len(errors) + len(player_errors)}")
    lines.append("Artifact states are research status, not blanket betting approval. /vip opens the member app.")
    return "\n".join(lines)



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

"""Independent Central-time daily moneyline scheduler with durable claims."""
import json
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .discord_daily import daily_moneyline, freeze_daily_moneyline
from .persistence.store import Store, digest


def daily_failure_notice(store, *, now=None):
    """Show one safe, date-scoped availability notice only after the scan window."""
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo("America/Chicago"))
    if (local.hour, local.minute) < (9, 15):
        return None
    date = local.date().isoformat()
    if daily_moneyline(store, now=now) is not None:
        return None
    audits = store.list_records("discord_daily_scan_audit", 5, entity=date)
    if not any(row["payload"].get("status") == "DATA_UNHEALTHY" for row in audits):
        return None
    return (
        f"⚠️ JABBAZI DAILY CHEAT SHEETS DELAYED • {date} CT\n"
        "Today's scheduled source scans failed data-health checks. "
        "No unverified or stale selections will be published. "
        "The research worker is retaining a private delivery audit for review."
    )


def run_due(settings, store, *, now=None, scanner_factory=None):
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo("America/Chicago"))
    if local.hour != 9 or local.minute >= 15:
        return "NOT_DUE"
    if daily_moneyline(store, now=now) is not None:
        return "ALREADY_FROZEN"
    date = local.date().isoformat()
    slot = local.minute // 5
    key = digest(["discord_daily_moneyline_scan", date, slot])
    if not store.append("discord_daily_scan_claim", date, {"slot": slot}, key):
        return "ALREADY_CLAIMED"
    from .automation import AutomaticScanner
    from .discord_sheets import archive_sheets
    scanner = (scanner_factory or AutomaticScanner)(settings, max_credits_per_run=int(os.getenv("JABBAZI_DISCORD_DAILY_SCAN_MAX_CREDITS", "15")))
    result = scanner.run("moneyline")
    sheet_id = archive_sheets(store, result)
    audit = {
        "status": "DATA_UNHEALTHY" if result.errors else "HEALTHY",
        "error_count": len(result.errors),
        "feeds_scanned": int(getattr(result, "feeds_scanned", 0) or 0),
        "quotes_archived": int(getattr(result, "quotes_archived", 0) or 0),
        "sheet_id": sheet_id,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    store.append("discord_daily_scan_audit", date, audit, digest(["discord_daily_scan_audit", date, slot]))
    # Never print raw scanner errors, response bodies, tokens or licensed quote rows.
    print("DISCORD_DAILY_SCAN_AUDIT " + json.dumps({
        "date": date, "slot": slot, "status": audit["status"],
        "error_count": audit["error_count"], "feeds_scanned": audit["feeds_scanned"],
        "quotes_archived": audit["quotes_archived"],
    }, separators=(",", ":")), flush=True)
    if result.errors:
        return "DATA_UNHEALTHY"
    sheet = next((row for row in store.list_records("research_sheet", 20, entity="latest_scan") if row["id"] == sheet_id), None)
    if sheet is None:
        return "SOURCE_UNAVAILABLE"
    frozen_id, created = freeze_daily_moneyline(store, sheet, now=datetime.now(UTC), timezone="America/Chicago")
    frozen = daily_moneyline(store, now=now)
    if frozen is None:
        raise RuntimeError("Daily sheet readback failed")
    payload = frozen["payload"]
    eligible = int(payload.get("eligible_game_count", -1))
    published = int(payload.get("row_count", -2))
    if eligible != published or payload.get("verified_count_match") is not True:
        raise RuntimeError("Daily slate/card count mismatch")
    print(
        f"DAILY_CHEAT_SHEET_VERIFIED DATE={date} ELIGIBLE={eligible} GAME_CARDS={published} SPORTS={','.join(payload.get('sports', []))}",
        flush=True,
    )
    if created:
        print(f"DISCORD_DAILY_FROZEN DATE={date} SHEET={frozen_id} SOURCE={sheet_id} SCAN_COMPLETED={sheet['payload']['completed_at']}", flush=True)
    return "FROZEN" if created else "ALREADY_FROZEN"


def daily_loop(settings, url, stop):
    # Own database connection; slow model refresh/settlement work cannot block 9 AM.
    store = Store(url)
    try:
        while not stop.is_set():
            try:
                status = run_due(settings, store) if settings.api_key else "NO_PROVIDER"
                if status not in {"NOT_DUE", "ALREADY_FROZEN", "ALREADY_CLAIMED"}:
                    print("DISCORD_DAILY_SCHEDULE_" + status, flush=True)
            except Exception as exc:
                print("DISCORD_DAILY_SCHEDULE_UNAVAILABLE_" + type(exc).__name__, flush=True)
            stop.wait(10)
    finally:
        store.close()

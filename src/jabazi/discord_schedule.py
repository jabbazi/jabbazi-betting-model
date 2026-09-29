"""Independent Central-time daily moneyline scheduler with durable claims."""
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .discord_daily import daily_moneyline, freeze_daily_moneyline
from .persistence.store import Store, digest


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
    if result.errors:
        return "DATA_UNHEALTHY"
    sheet = next((row for row in store.list_records("research_sheet", 20, entity="latest_scan") if row["id"] == sheet_id), None)
    if sheet is None:
        return "SOURCE_UNAVAILABLE"
    freeze_daily_moneyline(store, sheet, now=datetime.now(UTC), timezone="America/Chicago")
    return "FROZEN"


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

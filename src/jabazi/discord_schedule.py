"""Independent Central-time daily moneyline scheduler with durable claims."""
import json
import os
from dataclasses import replace
from decimal import Decimal
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


def scoped_non_mlb_daily_result(result, *, now=None):
    """Opt-in research-only recovery for one off-slate model-load failure.

    Never change the stored scan_run or use this for official picks. Incomplete
    provider data, additional errors, active MLB events, or stake-bearing
    actions all fail closed.
    """
    from .automation import AutomaticScanResult
    from .daily_scope import eligible_today

    if not isinstance(result, AutomaticScanResult):
        return None
    if tuple(result.errors) != ("baseball_mlb:score_model_load_ValueError",):
        return None
    now = now or datetime.now(UTC)
    slate = tuple(getattr(result, "slate_events", ()) or ())
    today = [event for event in slate if eligible_today(event, now=now)]
    if not today or any(event.get("sport") == "baseball_mlb" for event in today):
        return None
    if not result.feeds_scanned or not result.quotes_archived:
        return None
    for action in result.actions:
        decision = getattr(getattr(action, "decision", None), "value", "")
        if decision == "BET_NOW":
            return None
        try:
            if Decimal(str(getattr(action, "stake", 0) or 0)) != 0:
                return None
        except (ArithmeticError, ValueError, TypeError):
            return None
    # The scanner's persisted original error and all original decisions
    # remain unchanged. Only the separate daily research artifact is scoped.
    return replace(result, errors=())


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
    excluded = ()
    sheet_result = result
    if result.errors and os.getenv("JABBAZI_DAILY_OFF_SLATE_MODEL_RECOVERY", "false").lower() == "true":
        recovered = scoped_non_mlb_daily_result(result, now=now)
        if recovered is not None:
            sheet_result = recovered
            excluded = tuple(result.errors)
    sheet_id = (archive_sheets(store, sheet_result, source_model_exclusions=excluded)
                if excluded else archive_sheets(store, result))
    audit = {
        "status": "SCOPED_RESEARCH_ONLY" if excluded else "DATA_UNHEALTHY" if result.errors else "HEALTHY",
        "error_count": len(result.errors),
        "source_model_exclusions": list(excluded),
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
    if result.errors and not excluded:
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

"""Shared Central-time eligibility for daily feeds and final alert delivery."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
INACTIVE = {"cancelled", "canceled", "postponed", "suspended", "completed", "complete", "final", "finished", "closed", "invalidated"}


def eligible_today(row, *, now=None, pregame=True):
    now = now or datetime.now(UTC)
    value = row.get("starts_at_utc") or row.get("starts_at")
    try:
        start = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if start.tzinfo is None or now.tzinfo is None:
            return False
        if start.astimezone(CENTRAL).date() != now.astimezone(CENTRAL).date():
            return False
        if any(str(row.get(key, "")).lower() in INACTIVE for key in ("event_status", "status")):
            return False
        return not pregame or (start > now and not row.get("in_play"))
    except (ValueError, TypeError):
        return False


def reconciled_event(row, events, *, now=None):
    """Require the same provider event and start time; never reuse a moved forecast."""
    if not row.get('event_id') or not row.get('sport'):
        return False
    match = next((e for e in events if e.get('sport') == row.get('sport')
                  and str(e.get('event_id')) == str(row.get('event_id'))), None)
    if not match or not eligible_today(match, now=now) or not eligible_today(row, now=now):
        return False
    try:
        def start(r):
            return datetime.fromisoformat(str(r.get('starts_at_utc') or r.get('starts_at')).replace('Z', '+00:00'))
        return start(match) == start(row)
    except (ValueError, TypeError):
        return False


def delivery_eligible(store, rows, *, now=None):
    """Final queue guard using a fresh canonical scan, without mutating history.

    A missing event, moved start, inactive status, stale or incomplete scan fails
    closed. This is a recent provider observation, not a real-time status promise.
    """
    now = now or datetime.now(UTC)
    records = store.list_records('research_sheet', 1, entity='latest_scan')
    if not records or not rows:
        return False
    payload = records[0]['payload']
    try:
        observed = datetime.fromisoformat(str(payload.get('completed_at')).replace('Z', '+00:00'))
        if not payload.get('healthy') or payload.get('truncated') or not 0 <= (now-observed).total_seconds() <= 900:
            return False
    except (ValueError, TypeError):
        return False
    return all(reconciled_event(row, payload.get('slate_events', []), now=now) for row in rows)

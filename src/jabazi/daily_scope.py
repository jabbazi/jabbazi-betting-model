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

"""Read-only, bounded diagnostics from persisted scans; never provider responses."""

import re
from datetime import datetime
from uuid import UUID


_ERROR = re.compile(
    r"(?:(?:event_odds|model|model_load|score_model_load|player_model_load)_)?"
    r"(?:HTTPError|URLError|TimeoutError|ConnectionError|ValueError|TypeError|KeyError|"
    r"RuntimeError|OSError|AttributeError|IndexError|ZeroDivisionError|FileNotFoundError|"
    r"JSONDecodeError|OperationalError|IntegrityError)"
    r"|DUPLICATE_EVENT_IDENTITY|event_catalog_invalid"
)
_SPORT = re.compile(
    r"(?:americanfootball|baseball|basketball|icehockey|soccer|tennis|mma|golf|"
    r"aussierules|rugbyleague|cricket)_[a-z0-9_]{1,64}"
)
_SINGLE = {"MONTHLY_QUOTA_LIMIT", "player_prospective_report_unavailable"}
_STOP = {"MONTHLY_QUOTA_LIMIT", "PROVIDER_CREDIT_RESERVE"}


def safe_error(value):
    """Keep known generated codes, never arbitrary exception text/URLs/credentials."""
    if not isinstance(value, str):
        return "REDACTED_ERROR"
    if value in _SINGLE:
        return value
    parts = value.split(":")
    if len(parts) not in (2, 3) or not _SPORT.fullmatch(parts[0]):
        return "REDACTED_ERROR"
    if not _ERROR.fullmatch(parts[-1]):
        return "REDACTED_ERROR"
    if len(parts) == 3 and not re.fullmatch(r"[a-f0-9]{32}|player_[a-z0-9_]{1,64}", parts[1]):
        return "REDACTED_ERROR"
    return value


def recent_scan_health(store):
    summaries = []
    for row in store.list_records("scan_run", 20):
        payload = row["payload"]
        errors = payload.get("errors") or []
        try:
            scan_id = str(UUID(row["entity"]))
            completed = datetime.fromisoformat(payload["completed_at"]).isoformat()
        except (ValueError, TypeError, KeyError):
            continue
        stop = (payload.get("event_market_coverage") or {}).get("stop_reason")
        summaries.append({
            "scan_id": scan_id,
            "completed_at": completed,
            "healthy": payload.get("healthy") is True and not errors,
            "feeds_scanned": int(payload.get("feeds_scanned", 0)),
            "quotes_archived": int(payload.get("quotes_archived", 0)),
            "error_count": len(errors),
            "errors": [safe_error(error) for error in errors[:30]],
            "stop_reason": stop if stop in _STOP else None,
        })
    return summaries

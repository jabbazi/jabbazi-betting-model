"""App browsing dates; automatic alert delivery keeps its calendar-day guard."""
from datetime import UTC, datetime, timedelta
from ..daily_scope import CENTRAL


def default_slate_date(now=None):
    local = (now or datetime.now(UTC)).astimezone(CENTRAL)
    return local.date() + timedelta(days=int(local.hour >= 23))

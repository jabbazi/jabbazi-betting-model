"""One shared backup-first migration path for startup and explicit repair."""
from .discord_access import is_vip_name  # noqa: F401 -- compatibility import
from .discord_migration import migrate


def reconcile():
    result = migrate(apply=True, archive_obsolete=True)
    return {"status": "RECONCILED", **result}

"""One shared backup-first migration path for startup and explicit repair."""
from .discord_access import is_vip_name  # noqa: F401 -- compatibility import
from .discord_migration import migrate


def reconcile():
    result = migrate(apply=True, archive_obsolete=True)
    incomplete = any(w.startswith("DISCORD_OPERATION_") for w in result["warnings"])
    return {"status": "ARCHIVE_INCOMPLETE" if incomplete else "RECONCILED", **result}

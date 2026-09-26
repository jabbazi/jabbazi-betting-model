import os
from .sqlite import Ledger as LocalLedger


def ledger(path):
    url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
    if not url:
        if os.getenv("JABAZI_ENV", "development") == "production":
            raise RuntimeError("Production requires JABBAZI_PLATFORM_DATABASE_URL")
        return LocalLedger(path)
    from .store import Store

    if os.getenv("JABAZI_ENV", "development") == "production" and not url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError("Production persistence requires PostgreSQL")
    store = Store(url)
    try:
        if not store.ready():
            raise RuntimeError("Run the database migration command first")
    except Exception:
        store.close()
        raise
    return store

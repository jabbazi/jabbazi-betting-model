"""Read-only live-source readiness for the EXISTING V7 scanner.

Run ONLY in an already authorized isolated checkout; it neither calls paid
providers nor creates crosswalks or artifacts. Prints counts/reasons only.
"""
import json

from jabazi.models.player_registry import load_player_models
from jabazi.paid_readiness import read_v7_readiness


def main():
    store = None
    try:
        from jabazi.api import platform_store
        store = platform_store()
        models, errors = load_player_models(store)
        report = read_v7_readiness(store, models)
        report["model_load_error_count"] = len(errors)
        print(json.dumps(report, sort_keys=True))
        return 0 if not errors else 1
    except Exception:
        # Internal exception text may include DB paths or provider details.
        print(json.dumps({
            "status": "UNAVAILABLE", "reason": "READINESS_QUERY_FAILED",
            "provider_requests": 0, "betting_enabled": False,
            "database_writes": False,
        }, sort_keys=True))
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())

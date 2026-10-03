"""Apply the versioned platform schema as a separate deployment step."""

import os
from jabazi.config import load_dotenv
from .store import Store


def main():
    load_dotenv()
    url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
    if not url:
        raise SystemExit("JABBAZI_PLATFORM_DATABASE_URL is required")
    store = Store(url)
    try:
        store.migrate()
        if not store.ready():
            raise RuntimeError("Schema verification failed")
        print("Platform schema version 1 ready")
    finally:
        store.close()


if __name__ == "__main__":
    main()

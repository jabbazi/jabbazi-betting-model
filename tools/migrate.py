"""Apply the platform's versioned schema with the deployment migration credential."""

import os
from jabazi.config import load_dotenv
from jabazi.persistence.store import Store

if __name__ == "__main__":
    load_dotenv()
    url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
    if not url:
        raise SystemExit("JABBAZI_PLATFORM_DATABASE_URL must be configured")
    store = Store(url, initialize=True)
    print("platform_schema_version=1 ready=" + str(store.ready()))
    store.close()

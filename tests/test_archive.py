import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jabazi.domain.models import DataQuality, Quote
from jabazi.persistence.sqlite import Ledger
from jabazi.providers.base import ProviderBatch


class ArchiveTests(unittest.TestCase):
    def test_batch_archive_is_idempotent(self):
        now = datetime.now(timezone.utc)
        quote = Quote(
            "q",
            "e",
            "h2h",
            "Home",
            "draftkings",
            Decimal("2"),
            None,
            now,
            now,
            DataQuality.DELAYED,
            "baseball_mlb",
            "Away @ Home",
            now,
        )
        batch = ProviderBatch("fixture", now, b"[]", (quote,), 3, 497)
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "db.sqlite")
            self.assertEqual(ledger.archive_batch(batch), ledger.archive_batch(batch))
            count = ledger.connection.execute("SELECT COUNT(*) FROM quote_snapshots").fetchone()[0]
            self.assertEqual(count, 1)
            ledger.close()

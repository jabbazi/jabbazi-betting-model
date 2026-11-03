"""Dependency-free local ledger used for development and deterministic tests.

Production uses the PostgreSQL schema in migrations/001_initial.sql. This module
keeps the same append-only semantics so local scans survive process restarts.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jabazi.domain.models import Recommendation


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
              id TEXT PRIMARY KEY, betting_date TEXT NOT NULL, started_at TEXT NOT NULL,
              input_hash TEXT NOT NULL, status TEXT NOT NULL,
              UNIQUE (betting_date, input_hash)
            );
            CREATE TABLE IF NOT EXISTS raw_provider_payloads (
              sha256 TEXT PRIMARY KEY, provider TEXT NOT NULL, fetched_at TEXT NOT NULL,
              requests_used INTEGER, requests_remaining INTEGER, payload BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quote_snapshots (
              provider_quote_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,
              event_id TEXT NOT NULL, market_key TEXT NOT NULL, selection_key TEXT NOT NULL,
              sportsbook TEXT NOT NULL, decimal_odds TEXT NOT NULL, line TEXT,
              observed_at TEXT NOT NULL, source_timestamp TEXT NOT NULL, quality TEXT NOT NULL,
              sport TEXT, event_name TEXT, commence_time TEXT,
              FOREIGN KEY (payload_sha256) REFERENCES raw_provider_payloads(sha256)
            );
            CREATE TABLE IF NOT EXISTS recommendations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id TEXT NOT NULL,
              candidate_key TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
              sportsbook TEXT, decimal_odds TEXT, market_probability TEXT,
              adjusted_probability TEXT NOT NULL, ev TEXT, stake TEXT NOT NULL,
              max_playable_decimal TEXT, quote_ids_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE (scan_id, candidate_key),
              FOREIGN KEY (scan_id) REFERENCES scan_runs(id)
            );
            CREATE TABLE IF NOT EXISTS action_cards (
              fingerprint TEXT PRIMARY KEY, observed_at TEXT NOT NULL, event_id TEXT NOT NULL,
              event_name TEXT NOT NULL, sport TEXT NOT NULL, market_key TEXT NOT NULL,
              participant TEXT, selection_key TEXT NOT NULL, line TEXT,
              decision TEXT NOT NULL, reason TEXT NOT NULL, best_sportsbook TEXT NOT NULL,
              best_decimal TEXT NOT NULL, market_probability TEXT NOT NULL,
              market_relative_ev TEXT NOT NULL, model_probability TEXT, estimated_ev TEXT,
              stake TEXT NOT NULL, maximum_playable_decimal TEXT, stale INTEGER NOT NULL,
              in_play INTEGER NOT NULL, book_prices_json TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS action_cards_event ON action_cards(event_id, observed_at DESC);
            CREATE TABLE IF NOT EXISTS bets (
              id TEXT PRIMARY KEY, candidate_key TEXT NOT NULL, sportsbook TEXT NOT NULL,
              decimal_odds TEXT NOT NULL, line TEXT, stake TEXT NOT NULL,
              status TEXT NOT NULL, placed_at TEXT NOT NULL, settled_at TEXT,
              profit TEXT, UNIQUE(candidate_key, sportsbook, decimal_odds, line)
            );
            CREATE TABLE IF NOT EXISTS exposures (
              bet_id TEXT NOT NULL, tag TEXT NOT NULL,
              PRIMARY KEY (bet_id, tag), FOREIGN KEY (bet_id) REFERENCES bets(id)
            );
            """
        )
        self.connection.commit()

    def archive_batch(self, batch) -> str:
        """Persist raw evidence and normalized quotes atomically; duplicate payloads are harmless."""
        digest = self.input_hash(batch.raw_payload)
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO raw_provider_payloads VALUES (?,?,?,?,?,?)",
                (
                    digest,
                    batch.provider,
                    batch.fetched_at.isoformat(),
                    batch.requests_used,
                    batch.requests_remaining,
                    batch.raw_payload,
                ),
            )
            for quote in batch.quotes:
                self.connection.execute(
                    """INSERT OR IGNORE INTO quote_snapshots VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        quote.provider_quote_id,
                        digest,
                        quote.event_id,
                        quote.market_key,
                        quote.selection_key,
                        quote.sportsbook,
                        str(quote.decimal_odds),
                        str(quote.line) if quote.line is not None else None,
                        quote.observed_at.isoformat(),
                        quote.source_timestamp.isoformat(),
                        quote.quality.value,
                        quote.sport,
                        quote.event_name,
                        quote.commence_time.isoformat() if quote.commence_time else None,
                    ),
                )
        return digest

    def record_action_card(self, action, observed_at: datetime | None = None) -> bool:
        observed_at = observed_at or datetime.now(timezone.utc)
        card = action.price
        evidence = json.dumps(
            {
                "event": card.event_id,
                "market": card.market,
                "participant": card.participant,
                "selection": card.selection,
                "line": str(card.line),
                "prices": {book: str(price) for book, price in sorted(card.book_prices.items())},
                "decision": action.decision.value,
            },
            sort_keys=True,
        ).encode()
        fingerprint = self.input_hash(evidence)
        try:
            self.connection.execute(
                """INSERT INTO action_cards VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    fingerprint,
                    observed_at.isoformat(),
                    card.event_id,
                    card.event,
                    card.sport,
                    card.market,
                    card.participant,
                    card.selection,
                    str(card.line) if card.line is not None else None,
                    action.decision.value,
                    action.reason,
                    card.best_book,
                    str(card.best_decimal),
                    str(card.consensus_probability),
                    str(card.market_relative_ev),
                    str(action.model_probability) if action.model_probability is not None else None,
                    str(action.estimated_ev) if action.estimated_ev is not None else None,
                    str(action.stake),
                    str(action.maximum_playable_decimal)
                    if action.maximum_playable_decimal is not None
                    else None,
                    int(card.stale),
                    int(card.in_play),
                    json.dumps(
                        {book: str(price) for book, price in card.book_prices.items()},
                        sort_keys=True,
                    ),
                    "recommended",
                ),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def record_confirmed_bet(
        self,
        bet_id: str,
        candidate_key: str,
        sportsbook: str,
        decimal_odds: Decimal,
        line: Decimal | None,
        stake: Decimal,
        placed_at: datetime,
        exposure_tags: frozenset[str] = frozenset(),
    ) -> None:
        if stake <= 0 or decimal_odds <= 1:
            raise ValueError("Confirmed bet requires positive stake and decimal odds above 1")
        with self.connection:
            self.connection.execute(
                "INSERT INTO bets VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    bet_id,
                    candidate_key,
                    sportsbook,
                    str(decimal_odds),
                    str(line) if line is not None else None,
                    str(stake),
                    "open",
                    placed_at.isoformat(),
                    None,
                    None,
                ),
            )
            for tag in exposure_tags:
                self.connection.execute("INSERT INTO exposures VALUES (?,?)", (bet_id, tag))

    @staticmethod
    def input_hash(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def start_scan(self, scan_id: str, betting_date: str, payload: bytes) -> bool:
        try:
            self.connection.execute(
                "INSERT INTO scan_runs VALUES (?, ?, ?, ?, ?)",
                (
                    scan_id,
                    betting_date,
                    datetime.now(timezone.utc).isoformat(),
                    self.input_hash(payload),
                    "running",
                ),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def save_recommendation(
        self, scan_id: str, candidate_key: str, recommendation: Recommendation
    ) -> None:
        values = asdict(recommendation)
        encode = lambda value: str(value) if isinstance(value, Decimal) else value
        self.connection.execute(
            """INSERT INTO recommendations
            (scan_id,candidate_key,decision,reason,sportsbook,decimal_odds,market_probability,
             adjusted_probability,ev,stake,max_playable_decimal,quote_ids_json,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                scan_id,
                candidate_key,
                recommendation.decision.value,
                recommendation.reason,
                recommendation.best_sportsbook,
                encode(recommendation.best_decimal_odds),
                encode(recommendation.market_probability),
                encode(recommendation.adjusted_probability),
                encode(recommendation.ev),
                encode(recommendation.stake),
                encode(recommendation.max_playable_decimal),
                json.dumps(values["quote_ids"]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()

    def finish_scan(self, scan_id: str) -> None:
        self.connection.execute("UPDATE scan_runs SET status='complete' WHERE id=?", (scan_id,))
        self.connection.commit()

    def open_exposure(self) -> Decimal:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(CAST(stake AS REAL)), 0) value FROM bets WHERE status='open'"
        ).fetchone()
        return Decimal(str(row["value"]))

    def recommendation_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0])

    def close(self) -> None:
        self.connection.close()

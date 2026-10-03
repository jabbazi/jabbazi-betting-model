> Archived milestone document. See ../IMPLEMENTATION_STATUS.md and ../DEPLOYMENT.md for current behavior.

# Phase 1 design and operating contract

## Source of truth

PostgreSQL is the production source of truth. `Ledger` uses SQLite only as a dependency-free local
adapter for deterministic tests and offline development. Prices and model estimates are append-only.

## Decision sequence

1. Provider labels the origin and freshness of each quote.
2. Normalized selections are grouped into complete sportsbook markets.
3. Each complete book is proportionally de-vigged; the median cross-book probability is consensus.
4. Model probability receives an explicit uncertainty haircut.
5. EV is calculated at the best available price.
6. The minimum edge rises with existing daily exposure.
7. Fractional Kelly suggests a size, bounded by per-bet and daily hard limits.
8. The system persists the evidence and emits BET, WAIT, WATCH, or PASS.

`max_playable_decimal` is the minimum decimal price that preserves the required EV. For positive
American odds this means do not accept a numerically smaller price; for negative odds it means do
not accept a more negative price.

## Known Phase 1 limits

- The current consensus function covers two-outcome markets. Push-capable and three-way markets need
  explicit settlement-aware implementations.
- The current uncertainty haircut is deliberately conservative and must eventually be replaced by a
  versioned policy calibrated per model and market.
- The local ledger reserves scan capacity across sequential recommendations but does not create bets.
  Only confirmed placed bets affect persisted exposure.
- Provider entity mapping, closing-price jobs, settlement, calibration reports, and CLV calculations
  are represented in the production schema but require subsequent services.

## Next implementation slice

1. SQLAlchemy PostgreSQL repository and Alembic migrations.
2. Fixture/manual provider with raw-payload archival and mapping failures.
3. Licensed aggregator adapter behind environment-based credentials.
4. FastAPI endpoints for scans, recommendations, watches, and confirmed bet placement.
5. Closing snapshot and CLV worker.
6. Integration tests against disposable PostgreSQL.

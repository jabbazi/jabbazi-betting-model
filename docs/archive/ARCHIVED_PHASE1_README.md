> Archived milestone document. See ../IMPLEMENTATION_STATUS.md and ../DEPLOYMENT.md for current behavior.

# Jabazi Guru System V2 — Multisport

An auditable sports-betting analytics and execution-support platform. It does not promise winning
picks and does not place wagers. Its job is to compare calibrated probability estimates with
no-vig market prices, enforce risk limits, preserve every decision input, and measure CLV.

## Phase 1 status

Implemented foundation:

- Decimal-safe American/decimal odds, implied probability, no-vig, EV, and Kelly-reference math
- Cross-book consensus pricing and best-price selection
- Uncertainty-adjusted BET / WAIT / WATCH / PASS engine
- Increasing edge threshold as daily exposure grows
- Hard daily and per-bet exposure ceilings
- Explicit real-time/delayed/cached/manual/fixture provenance
- Persistent, cumulative and idempotent local scanner ledger
- PostgreSQL audit schema with immutable odds snapshots
- CLV, Brier-score, and calibration-bucket primitives
- Provider boundary that forbids silently fabricated fields
- Credential-backed The Odds API adapter for explicitly selected sports and markets
- Universal sport and market catalog merged from the uploaded multisport starter
- Event-scoped props, period-market, and alternate-line ingestion
- Same-rung price shopping that never mixes alternate lines
- Persistent raw provider payload and normalized quote archive
- Runnable `catalog`, `events`, `scan`, and `scan-event` CLI commands
- Unit and end-to-end scanner tests
- Authenticated FastAPI bridge for the Jabbazi Scanner website

Not yet implemented: scheduled production ingestion, validated sport-specific models,
settlement feeds, CLV jobs, promotions, parlays, live betting, alerts, and UI. Those require later
milestones and, where applicable, licensed data.

## Local verification

Python 3.12 or newer:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Start PostgreSQL with `docker compose up -d db`, then apply `migrations/001_initial.sql` using your
preferred PostgreSQL migration runner. Copy `.env.example` to `.env`; never commit the result.

## Safety invariants

- Cached and fixture quotes cannot produce `BET_NOW`.
- Incomplete two-sided markets cannot be de-vigged and become `WATCH`.
- Recommendations never become placed bets automatically.
- Once daily capacity is exhausted, risk policy vetoes further bets.
- Same canonical input cannot create a second scan for the same betting date.

See [Phase 1 design](docs/phase-1.md) for boundaries and next work.
See [Setup and operations](docs/SETUP.md) for the complete step-by-step runbook.
See [Cloud deployment](docs/CLOUD.md) for the always-on scanner configuration.
See [Website integration](docs/WEBSITE-INTEGRATION.md) for the secure scan-button connection.

## Independent MLB probability model

The first independent model is an MLB moneyline Elo pipeline. It processes games
chronologically, holds the newest season out, and refuses production approval
unless it has enough two-sided historical market comparisons and beats the
no-vig market on both Brier score and log loss.

```powershell
.\jabazi.ps1 backfill-mlb --seasons 2021,2022,2023,2024,2025,2026 --output data/mlb_games.json
.\jabazi.ps1 train-mlb --input data/mlb_games.json --output models/mlb_moneyline.json
```

An artifact that misses any gate remains shadow-only. The scanner may display
its probability as WATCH evidence, but it cannot turn that estimate into
`BET_NOW`.

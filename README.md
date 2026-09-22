# JABBAZI sports research platform

**Research infrastructure, not a production-approved betting service.** No model
in the active registry can produce approved paid picks. The platform does not place bets.

This repository preserves the recovered MLB scanner and adds MLB/NFL/CFB shadow
baselines, audited pricing, central portfolio reservations, PostgreSQL-capable
storage, an authenticated API, and research frameworks for calibration, props,
alternates, correlated parlays, and historical execution evaluation.

Start with [the implementation audit](docs/IMPLEMENTATION_STATUS.md),
[deployment instructions](docs/DEPLOYMENT.md), and [mathematical conventions](docs/MATH.md).
Documents in `docs/archive` describe older milestones and are not deployment instructions.

## Install and verify

Requires Python 3.12 or later.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install '.[dev]'
python -m pytest -q
ruff check src tools tests --select F
python tools/smoke_api.py
```

SQLite integration tests run locally. Set `JABBAZI_TEST_POSTGRES_URL` to a dedicated
test database to run the transaction, concurrency, lifecycle, and immutability
tests against PostgreSQL. CI supplies an ephemeral PostgreSQL 17 service.

## Local research API

Copy `.env.example` to `.env`; configure a database URL and a random service token.
Use `sqlite:///platform-local.db` only for development or PostgreSQL for production.

```bash
python -m jabazi.persistence.migrate
uvicorn jabazi.api:app --host 127.0.0.1 --port 8000
```

OpenAPI is at `/docs`. `/healthz` is liveness; `/readyz` verifies the database schema
and explicitly reports that model approval remains disabled. All `/v1` data and
scan endpoints require `Authorization: Bearer <service-token>`. Scan requests
consume provider quota when a real API key is configured.

## Model training

No private data, live ledger, or model artifacts are committed. Existing trained
MLB/NFL research artifacts remain in the earlier saved starter. Reproduce them:

```bash
python -m jabazi history --sport nfl --as-of 2026-09-22 --output data/nfl_history.json
python -m jabazi train-baseline --sport nfl --input data/nfl_history.json --output models/nfl_baseline.json --holdout 2025
```

Use the actual cutoff date for a new snapshot. The 2024 tuning / 2025 holdout
convention is documented in `docs/MODEL_REPORT.md`; retain a new untouched
evaluation period before developing additional features. MLB supports the same
workflow. CFB requires `JABBAZI_CFBD_API_KEY`. Every baseline stays `SHADOW_ONLY`,
including when an artifact's approval flag is manually changed.

## Discord

`python tools/discord_setup.py` prints the server plan without contacting Discord.
The explicit `--apply` option requires an owner-controlled server and configured bot.
`python -m jabazi.discord_review` previews research cards; its explicit `--send`
option sends to the verified private review channel. Delivery is off by default.
Paid memberships, public pick distribution, and billing are not implemented.

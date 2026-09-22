# Deployment runbook — research service

Deployment, external authentication, Discord permission checks, and recovery tests
must succeed on the chosen host before calling this operational. No cloud resource
has been provisioned by this build.

## Services

1. PostgreSQL 17 with durable storage, backups, and a tested restore procedure.
2. One-off migration: `python -m jabazi.persistence.migrate`.
3. API: `uvicorn jabazi.api:app --host 0.0.0.0 --port 8000` behind HTTPS.
4. One scanner worker: `python -m jabazi daemon --mode quick --interval 7200`.

The database-backed lease excludes overlapping scanners. Reservation transactions
serialize capacity checks. Redis is not required. The two-hour research cadence
does not promise timely pregame or closing coverage. The daemon minimum interval
is five minutes; measure provider quota and event coverage before increasing cadence.

## Required host configuration

| Variable | Purpose |
|---|---|
| `JABAZI_ENV=production` | Refuse legacy/local production storage |
| `JABBAZI_PLATFORM_DATABASE_URL` | PostgreSQL URL; URL-encode credentials |
| `JABBAZI_MODEL_TOKEN` | Random bearer token, at least 32 characters |
| `JABAZI_ODDS_API_KEY` | Licensed live odds account |
| `JABAZI_BANKROLL` | Reviewed current bankroll; sample values are not account balances |
| `JABAZI_UNIT_SIZE` | Single unit setting, default 30 |
| `JABBAZI_CURRENT_DRAWDOWN` | Reviewed drawdown fraction; automatic reconciliation pending |
| `JABBAZI_JURISDICTION` | Defaults to LA, excluding CFB player props |

Mount `models/` and `config/` read-only. Mount `/data` persistently for worker health
and the optional private Discord delivery journal. Model artifacts and current
event context are provisioned separately. API readiness does not approve a model
or assert that an external feed is healthy.

## Docker Compose

`docker-compose.yml` starts a localhost-only development database. The cloud file
supplies database, migration, API, and worker services. Create `.env`, set
`JABBAZI_POSTGRES_PASSWORD`, and point the platform URL to hostname `db`.
The API binds localhost:8000; configure TLS and the website proxy on the host.

```bash
docker compose -f docker-compose.cloud.yml config --quiet
docker compose -f docker-compose.cloud.yml up -d --build
```

Docker was unavailable in the editing environment; the Docker image build and CLI
check passed in [GitHub CI](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35782687953).
Verify the full Compose runtime on a Docker-capable host. Keep database ports private. Use a
restricted runtime role after an owner applies migrations; deny schema/trigger
changes to that role. Evidence triggers reject ordinary UPDATE, DELETE, and TRUNCATE.
A privileged database owner can remove protections, so access controls and backups
are still required; this is not external cryptographic notarization.

## Acceptance and recovery

- Verify health/readiness, unauthorized 401 responses, and a real authenticated scan.
- Restart a worker; check reservation idempotency and lease recovery.
- Interrupt database/provider access; verify no BET_NOW or Discord delivery occurs.
- Inspect source timestamps, quota accounting, and per-sport model status.
- Restore a backup separately; compare event counts and payload hashes.
- Reconcile placed wagers and corrections against original sportsbook evidence.
- Check Discord free/VIP visibility with test accounts before enabling the webhook.

Baselines remain shadow-only even when infrastructure checks pass. Paid picks still
require historical odds, fitted features, calibration, prospective evidence, and
market-specific approval controls described in the implementation audit.

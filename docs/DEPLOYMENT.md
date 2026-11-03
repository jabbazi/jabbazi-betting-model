# Deployment runbook — research service

Deployment, external authentication, Discord permission checks, and recovery tests
must succeed on the chosen host before calling this operational. No cloud resource
has been provisioned. Start with [GO_LIVE.md](GO_LIVE.md) for the prepared Render
deployment and cost review.

## Services

1. PostgreSQL 17 with durable storage, backups, and a tested restore procedure.
2. One-off migration: `python -m jabazi.persistence.migrate`.
3. API: `python -m jabazi.runtime api` behind HTTPS; uses `PORT`, default 8000.
4. Worker: `python -m jabazi.runtime worker`.

The worker runs research scans every two hours and checks upcoming events every
30 seconds; event catalogs are cached for five minutes. Targeted snapshots run
near 90 and 30 seconds before scheduled starts. Quota limits, schedule changes or
outages can leave gaps. Fresh pre-start same-contract complete markets from at
least two books qualify as closing proxies, not certified closing lines. Missing
odds credentials produce a waiting heartbeat every five minutes and no request.

Database leases limit overlapping work. Transactions serialize portfolio checks,
quota reservations and delivery claims. Redis is not required. The UTC calendar-month
credit ceiling is shared by API scans, the worker and historical imports using
this database. Failed requests retain reservations. This conservative local
allowance is not the provider's billing counter.

## Required host configuration

| Variable | Purpose |
|---|---|
| `JABAZI_ENV=production` | Refuse legacy/local production storage |
| `JABBAZI_PLATFORM_DATABASE_URL` | PostgreSQL URL; URL-encode credentials |
| `JABBAZI_MODEL_TOKEN` | Random bearer token, at least 32 characters |
| `JABAZI_ODDS_API_KEY` | Licensed live odds account |
| `JABAZI_BANKROLL` | Reviewed current bankroll; sample values are not account balances |
| `JABAZI_UNIT_SIZE` | Single unit setting, default 30 |
| `JABBAZI_MONTHLY_CREDIT_LIMIT` | Shared request ceiling, default 3000 |
| `JABBAZI_SCAN_INTERVAL_SECONDS` | Scan cadence, default 7200, minimum 300 |
| `JABBAZI_SCAN_MAX_CREDITS` | Per-worker-scan allowance, default 9 |
| `JABBAZI_CURRENT_DRAWDOWN` | Reviewed drawdown fraction; automatic reconciliation pending |
| `JABBAZI_JURISDICTION` | Defaults to LA, excluding CFB player props |

Keep secrets in host configuration. Mount `models/` and `config/` read-only where
used. Artifacts and current event context are provisioned separately. Render needs
no application disk for ledger, quotas, heartbeats or delivery, which use PostgreSQL.
The Compose template retains an optional legacy volume. API readiness checks the
database; it does not approve models, probe feeds or establish heartbeat freshness.

Private Discord delivery is disabled by default. Enabling it requires the configured
bot token, guild, owner, analyst role, review channel and webhook in `.env.example`.
Production verifies owner identity and explicit channel overwrites before sending.
Owners and administrators bypass Discord visibility restrictions. A delivery claim
is committed before HTTP; ambiguous sends are recorded for review, not silently retried.

## Docker Compose

`docker-compose.yml` starts a localhost-only development database. The cloud file
supplies database, migration, API, and worker services. Create `.env`, set
`JABBAZI_POSTGRES_PASSWORD`, and point the platform URL to hostname `db`.
The API binds localhost:8000; configure TLS and the website proxy on the host.

```bash
docker compose -f docker-compose.cloud.yml config --quiet
docker compose -f docker-compose.cloud.yml up -d --build
```

[CI run 35784881693](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35784881693)
passed 127 tests and the disposable Docker/PostgreSQL API/worker stack. Real HTTP
verified authentication, owner ledger import/settlement and worker waiting status.
A separate restore retained both synthetic evidence hashes; stopping PostgreSQL
produced readiness/scan 503 responses. **Never run synthetic CI ledger scripts
against a live database.** Actual host provisioning and recovery remain separate.

Keep database ports private. The initial Render template uses its supplied database
owner connection for migrations and runtime. Before commercial operation, provision
a restricted runtime role and separate migration role; deny schema/trigger changes
to runtime. Evidence triggers reject ordinary UPDATE, DELETE, and TRUNCATE.
A privileged database owner can remove protections, so access controls and backups
are still required; this is not external cryptographic notarization.

## Operations and historical evidence

- `python -m jabazi.runtime doctor`: configuration/database check, no feed probe.
- Authenticated `/v1/operations`: worker/collector history, delivery results and quota reservations.
- `/v1/ledger`, `/v1/ledger/import`, settlement/history/CLV routes: owner-reported wagers and corrections.
- `/v1/closing-lines`: archived proxies; `/v1/performance`: explicitly owner-reported results.
- `/docs`: generated contracts. All `/v1` operations require a bearer token.

Inspect heartbeat timestamps and nested scan/collector errors. Independent stale
heartbeat alerting remains to be configured on the host. Licensed historical
collection is explicit and consumes quota:

```bash
python -m jabazi.runtime history --sport americanfootball_nfl --at 2025-09-07T16:00:00Z
```

This reserves 30 credits for three main markets, retains the actual provider
snapshot time, and rejects snapshots later than the requested cutoff. Historical
payloads are research-only and cannot become fresh live quotes. This example is
not an automatically executed request or a backtest result.

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

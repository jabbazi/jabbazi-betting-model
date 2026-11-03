# Render research deployment — September 22, 2026

Live infrastructure checks succeeded for source commit
`32c7f575fb963f5db4b17e64a5eebb5bbe52a4b2` after the owner supplied the missing
bankroll configuration. No bankroll amount, token or provider credential is
included in this public record.

- Render reported API deployment succeeded and live; schema migration completed.
- Render reported worker deployment succeeded and live; schema migration completed.
- The worker emitted a real heartbeat with `WAITING_FOR_ODDS_CREDENTIAL` and
  `betting_enabled: false` at 2026-09-22T22:29:17Z.
- The public API's `/healthz` returned HTTP 200.
- `/readyz` returned HTTP 200, database ready and betting disabled.
- An unauthenticated request to `/v1/operations` returned HTTP 401.

The missing-bankroll worker failure is resolved. The initial API deployment ran
an older build; both services were rebuilt using the corrected source above.
Environment changes affect the existing services; no additional service was
created during this repair.

This verifies research infrastructure startup only. Real odds authentication,
collection and closing coverage; Discord delivery; host backup restoration;
restricted runtime database permissions; independent monitoring; and model
approval remain unverified. No live odds key was configured during these checks.
Models remain shadow-only and paid picks are not enabled. Owner-reported ledger
endpoints have CI coverage but were not populated with synthetic wagers on the
live database.

See [the launch checklist](GO_LIVE.md) and [deployment runbook](DEPLOYMENT.md)
for remaining configuration and acceptance work.

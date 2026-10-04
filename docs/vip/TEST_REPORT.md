# VIP release verification — 2026-09-30 UTC

## Passed

- PR #54 merged after GitHub Actions run 36666523340: 610 tests with PostgreSQL, lint, API smoke tests, container readiness/outage checks and disposable database backup/restore.
- Local full suite: 596 tests passed.
- Isolated Playwright Chromium browser tests: 390px phone and 1440px desktop, no horizontal overflow or page errors. Ticket login, home, alias search, detail, watchlist, unit preference persistence, unqualified Top 10 empty state, sports, and offline research clearing passed. Synthetic fixtures stayed in CI; screenshot artifact `vip-browser-evidence` is attached to the workflow.
- Production API commit 2bfd19cf9a3851192b707dd523d145860c05f8c4 deployed; `/readyz` 200, `/vip` 200 serves terminal, anonymous `/v1/vip/home` 401.
- Production worker same commit deployed. Discord gateway ready; vip/cheatsheet/alerts/support registered. Reconciliation verified 18 active channels, four VIP roles, bot without Administrator, required hierarchy, and all 18 introductions pinned. Existing banner read back without reposting.

## Blocked / unverified

The worker's real-owner acceptance probe at 03:59:20 UTC returned `sign_in_http: 503`. Login therefore is NOT production-verified and the application is NOT launch-complete. Discord current-role verification is unavailable in the API service. The API requires `JABBAZI_DISCORD_BOT_TOKEN`, plus the guild/owner configuration. The connector can write known environment values but cannot read/copy the worker's existing secret. Guild and owner IDs were configured via the connector; the bot credential must be supplied securely in Render. Do not paste it in chat. No authorization check was disabled.

After fixing configuration, redeploy the API, restart the worker, and require `VIP_ACCEPTANCE_VERIFICATION` status VERIFIED. Then run a real phone `/vip` launch and VIP-role removal test. No real member join or phone interaction was performed in this release. Browser tests use isolated identities; role-revocation/IDOR tests use simulated Discord responses.

## Limits

See RUNBOOK.md for COMPLETE/PARTIAL/BLOCKED/PLANNED feature scope. Current model validation and canonical ledger evidence govern available results; empty qualified lists are expected. Production backup restoration, browser push, correlated parlay building, full per-sport multi-market sheet versioning, and exhaustive 90-item acceptance are not claimed complete.

# Production cleanup checkpoint — 2026-09-29

## Verified baseline

- Repository: `jabbazi/jabbazi-betting-model`.
- Deployment branch in the current Render blueprint: `build/production-foundations`.
- Inspected head: `ec47445c71cd3017f454ff061f81a518f656063a` (PR #37). PRs #32, #36, and #37 are merged.
- Live public `/healthz` and `/readyz` both returned HTTP 200. Readiness reported `database=ready`, `betting_enabled=false`. These endpoints do not establish Discord, worker, provider, or model health.
- Discord browser access reached a sign-in page; no server inventory or competitor community was accessible.
- Render connector returned `no workspace selected`; its available workspace is named `My Workspace`. Connector requires owner confirmation of workspace before service inspection. No workspace was selected automatically.
- No live channel, role, permission, deployment, environment variable, billing setting, or message was changed in this run.

## Prepared repair

- Twenty active text channels in the owner's seven requested categories. Preserve IDs when renaming `vip-parlays`, `daily-results`, and `open-a-ticket`; archive legacy channels without deleting messages.
- A shared migration path reads inventory and commands, verifies the owner, persists a database backup and reads it back before any mutations, and simulates free/VIP/owner/bot access after applying changes. Both duplicate canonical VIP roles are retained. New private categories are created with privacy overwrites in the same request.
- Explicit approved VIP names and configured IDs replace substring matching. Expired/waitlist/"not VIP" names do not confer access.
- Slash commands actually populate the guild command tree before sync. `/vip` and `/cheatsheet` fetch current membership and respond privately. `!vip` uses DM, then a private non-invitable thread. No billing record is required for a manual VIP role.
- Alert assignment only accepts unique, unprivileged, manageable alert roles. Support uses a private thread with a category selection.
- The immutable daily sheet keeps the full slate, uses a single delivery with a complete attachment for long sheets, selects one lean per event, and retains unavailable events. `/cheatsheet` only retrieves the stored snapshot. A worker restart recognizes an existing freeze before spending scan credits; the freeze references the exact dedicated moneyline scan.
- Official Main Card rejects stale/in-play quotes, unsupported stages, and quarantined anomalies, while retaining the existing cash-authority requirement. Play-to and Central-time posting are displayed.
- Results exclude user-origin bets and sprinkles. Best-2 remains research and normalizes PRICE CHECK; the renderer no longer implies a default 2u recommendation.
- Scanner status uses an editable panel rather than a new message every heartbeat. Publishing lanes fail independently. HTTP failures log lane/operation/status without response bodies or credentials.

## Deployment prerequisites and remaining live verification

1. Confirm the Render workspace, inspect both deployed services, deployed commits, environment variable names/IDs (never print secret values), worker logs and gateway errors.
2. Authenticate Discord and inspect the actual guild, integrations, role hierarchy, overrides, existing content and other legitimate community access before approving the migration inventory.
3. Review the backup and migration dry run. Ensure the bot has Manage Channels, Manage Roles, View/Send/Read, Manage Messages, Embed Links, Attach Files, private-thread creation and thread sending as required. Do not add Administrator. Move its role above roles it needs to assign through owner-authorized controls.
4. Confirm CI against the final PR head; merge only after the live inspection is complete. Existing Render configuration uses `checksPass` auto-deploy, so do not trigger a duplicate deploy after merge.
5. Apply the reviewed migration, synchronize channel IDs for any newly created destinations, and seed reviewed onboarding using `tools/seed_discord_content.py --apply`. The seed tool updates only this bot's own marked onboarding messages; it does not edit picks or results.
6. Billing must use a distinct configured `JABBAZI_DISCORD_BILLING_ROLE_ID` before automatic grant/revoke can operate. The manual VIP role is intentionally never a billing-reconciliation target. Inspect existing billing provenance and migrate it deliberately; do not revoke legitimate manual access.
7. Verify Message Content intent for `!vip`, slash-command registration, gateway startup, bot/application branding, permission simulations, private support visibility, alerts, and destination IDs. Existing startup migration receipts may suppress a previous v1 migration; run the reviewed migration explicitly instead of assuming a restart applies it.
8. Verify the next 9 AM America/Chicago dedicated scan, freeze record and single delivery. The worker currently checks a 09:00–09:14 window with five-minute retry slots; long earlier jobs or downtime can delay/miss that window. Exact 9 AM scheduling still needs live timing verification and potentially an independently scheduled worker path. Do not fabricate today's sheet after the fact.
9. Confirm durable delivery outcomes, no repeated 401/403/429 failures, no duplicate posts and no false official recommendations. Status updates edit only status, never frozen research or settled history.
10. Complete live results-period/CLV reporting and gateway crash supervision assessment. This change does not claim new daily/weekly/monthly settlement summaries, verified closing lines, billing activation, moderation rules, or live source-sheet ingestion.

## Owner smoke test after deployment

Give a test account JABBAZI VIP; confirm premium sections appear; run `!vip`, `/vip`, `/cheatsheet`, `/alerts`, `/support`; confirm a free account cannot see premium sections and neither account can see staff/archive.

The server is not yet certified complete. Local simulated tests are not a substitute for this live verification.

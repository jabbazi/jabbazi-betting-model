# JABBAZI V6 — evidence-based release verification ledger

**As of 2026-10-28 UTC. Release verdict: HOLD / RESEARCH_ONLY / PASS.**

This file records actual checks performed with the authorized GitHub, Render and
JABBAZI Research connectors. `VERIFIED` applies only to the **narrow claim**
explicitly listed; it never implies full betting approval. This is a
point-in-time record, not a live monitoring dashboard. New evidence must be
dated and independently rechecked before a status change.

## Evidence and release gates

| Gate | Status | Verified claim or missing proof |
| --- | --- | --- |
| Development CI on PR #80 | **VERIFIED — DEVELOPMENT ONLY** | Commit `90f78143988169a5b89e8d41d31afad8d04d339f`; GitHub Actions [#40641660042](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/40641660042) completed successfully with **1,097 pytest passed, one warning**, green container and VIP-browser jobs. |
| Production Research API availability | **VERIFIED — SERVICE UP ONLY** | Render Research API service `srv-dapfgeff3r2c73citeog` LIVE at `8ede9800b85ff5073db95de731d8d9a26b978e53`; healthcheck `GET /readyz` returned **200 OK** repeatedly around 2026-10-28 06:09–06:10 UTC. It is NOT running PR #80. |
| Production Discord worker availability | **VERIFIED — PROCESS UP ONLY** | Render Worker `srv-dapfub1srm7s73fbo7cg` LIVE at same prior commit; worker diagnostics show `discord_process=RUNNING`, with internal closing collection sometimes `HEALTHY`. This does **not** verify Discord publishing. |
| Discord status-channel delivery | **FAILED / ACTION REQUIRED** | Existing worker logs from 2026-10-28 05:00–06:11 UTC contain **69** `DISCORD_RESOURCE_FAILURE lane=status` entries reporting `GET /channels/<redacted> HTTP 404`; the channel may be deleted, inaccessible or misconfigured. A running worker is not a successful send. Verify current guild/channel ID, channel visibility and bot access with authenticated Discord administration. Avoid guessing a replacement ID or deleting historical messages. |
| Discord official-pick delivery | **FAILED / ACTION REQUIRED** | Same log query returned **69** `DISCORD_PUBLISH_OFFICIAL_PICKS_ValueError_HTTP_None` entries. Root cause is not established from safe error-class logs. Inspect authorized Discord channel/permission and member-origin configuration, then verify a controlled non-betting publish transaction with durable delivery receipt. Do not infer delivery from heartbeat or scan success. |
| NBA paid player-prop API access | **PARTIAL / NOT RELEASE-VERIFIED** | Historic BALLDONTLIE sampled single-game props: 2,628 rows on 2026-10-27 19:18 UTC, but 0 on 2026-10-28 02:36 UTC. Re-run full eligible pregame slate in a securely authorized runtime; verify priority categories, pagination, timestamps, multi-book coverage and entitlement. |
| NFL paid player-prop API access | **PARTIAL / NOT RELEASE-VERIFIED** | Historic BALLDONTLIE sample: 81 rows on 2026-10-27 19:19 UTC and 2026-10-28 02:37 UTC. Neither confirms future full slate or all required markets; verify Eastern-date/UTC kickoff handling. |
| NHL paid player-prop API access | **NOT VERIFIED** | No authenticated NHL paid player-prop response or complete-game coverage was observed in the production logs examined. A `/v1/vip/matchup/NHL/...` 200 is unrelated to paid-prop entitlement. |
| Real NBA/NFL/NHL player-model validation | **NOT VERIFIED / NOT APPROVED** | Deployed model-status tool reports `VALIDATING` with **zero** prospective player-bucket samples for each of the three sports. Historical training/holdout work is not prospective approval. |
| NBA/NHL exact-ticket joint calibration | **NOT VERIFIED / NOT APPROVED** | No real pregame frozen forecasts, settled final-game outcomes, authentic source receipts, event-disjoint sufficient prospective samples, or externally verified paired exact-ticket baselines. Mock tests are not observations. |
| Executable sportsbook SGP quote / boost rules | **NOT VERIFIED** | No independently authenticated current same-book complete-ticket quote or verified promotion eligibility, stake cap, or settlement rules. Do not multiply marginal leg probabilities or infer a no-vig combined quote from one side. |
| Production VIP/Discord end-to-end V6 | **NOT VERIFIED** | CI verifies an isolated HTTPS staging VIP API and simulated user flow. Actual production Discord `!vip`/VIP access and delivery on the proposed feature head remain untested; PR #80 is unmerged. |
| V6 production deployment | **NOT DEPLOYED — INTENTIONALLY BLOCKED** | Both existing services remain live on prior commit; no merge, migration, new service, secret export, allowlist relaxation, or production rollout was authorized by the available evidence. |

## Verification contract

- Do not change a gate to VERIFIED using synthetic fixtures, a guessed provider response,
  owner-entered hit probabilities, copied source payloads, or a green unit-test run.
- Keep `RESEARCH_ONLY`, `PASS`, `betting_enabled=false` until all the
  relevant provider/model/price/Discord acceptance gates pass independently.
- A successful API healthcheck does not verify Discord messages, VIP user
  entitlements, model calibration, or executable sportsbook quotes.
- Do **not** relax the PostgreSQL IP allowlist or place Render secrets into
  GitHub Actions to enable a test. Current hosted connectors cannot run an
  authenticated private Render shell or query the network-restricted database.
- An authorized private runtime must execute
  `python -m tools.boost_live_acceptance_matrix` against a verified,
  pregame NBA/NFL/NHL schedule with the existing provider key, with
  sanitized per-game, per-market, and per-book counts and source timestamps.
- Discord requires an authorized channel-permissions and message-delivery
  verification; no connector here can assert that a missing channel has
  been recreated or grant bot permissions.
- Prospective game-result collection and calibration require actual
  future observations; they cannot be accelerated through synthetic tests.

**Release sign-off:** blocked by Discord delivery failures, unverified NHL/full
paid feed coverage, zero approved prospective player/joint calibration samples,
lack of independent executable sportsbook quotes, and missing full
production-end-to-end acceptance.

No production changes were made while recording this evidence.

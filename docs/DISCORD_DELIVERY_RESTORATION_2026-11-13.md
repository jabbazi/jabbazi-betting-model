# Discord + daily cheat-sheet production restoration — 2026-11-13

**Status: ACTION REQUIRED / DEVELOPMENT ONLY. No production merge or deployment.**

## Read-only evidence

- Render Worker: `srv-dapfub1srm7s73fbo7cg`, live deployment `dep-dbl6p90m7kps739eetcg`, production commit `b92b2ccde73d4a31d4330f394375baedf617b243`.
- Render API: `srv-dapfgeff3r2c73citeog`, live deployment `dep-dbl6oks9v7es73av3blg`, same production commit.
- November 13 Worker logs: recurring `DISCORD_PUBLISH_STATUS_HTTPStatusError_HTTP_404` with `DISCORD_RESOURCE_FAILURE lane=status resource=/channels/1554622841201365072 http=404`. This is a **status-lane** channel lookup; do not infer that the sheet destination is identical or that a channel was deleted. It can also mean inaccessible or misconfigured.
- November 13 daily schedule: `DISCORD_DAILY_SCHEDULE_DATA_UNHEALTHY` at 15:00, 15:05, 15:10 UTC (09:00/09:05/09:10 America/Chicago). The daily scheduler deliberately refuses to freeze or publish incomplete scan output.
- Runtime `discord_process=RUNNING` does not prove sending permissions, delivery, or valid paid model inputs. `betting_enabled=false` is intentional and **must not be flipped** to repair research notifications. `discord_entitlements=UNCONFIGURED` requires a separate reviewed authorization check.

## Development changes in this PR

1. Durable, credential-safe per-slot scan health audit (feed count, quote count, error count, archived sheet ID) without raw provider error messages or licensed rows.
2. One date-scoped, no-mention **availability notice**, after the 09:00–09:15 scan window, if the daily sheet was not frozen because source scans were unhealthy. No fabricated picks, stale prices, or automatic uncertain-delivery retries.
3. Existing read-only Discord verifier now checks whether the configured status and cheat-sheet IDs appear among the channels visible to the bot. It reports missing/inaccessible IDs without changing channels or permission overwrites.
4. Regression tests for audit privacy, scan claim idempotency, delayed notice timing, and single-send claims.

The actual data-feed failure type **cannot** be determined from the existing generic `DATA_UNHEALTHY` lines alone. This change improves diagnostics for subsequent authorized runs; it is not proof of a repaired feed.

## Additional targeted development recovery (off by default)

The Worker quick-scan results from November 9–13 repeatedly included the single error
`baseball_mlb:score_model_load_ValueError`. Model refresh logs identify an unavailable
MLB score model due to missing recent completed-game coverage. **The dedicated 09:00
moneyline scan's exact error array was not accessible through external read-only
database tooling**, so attribution to the daily job is a strong hypothesis rather
than a proven root cause.

Development-only opt-in:
`JABBAZI_DAILY_OFF_SLATE_MODEL_RECOVERY=true`

This flag is **unset/false by default**. When explicitly enabled after staging
verification, it permits a separate daily *research-only* snapshot to be frozen
only when ALL the following are true:

- The full source scanner has exactly one error, the specific MLB score-model
  load failure named above.
- There is at least one eligible current-day pregame event, and no eligible
  MLB event that day.
- The source actually scanned feeds and archived quotes.
- There are no stake-bearing or BET_NOW actions, even in the original
  failing scan.
- The scoped snapshot carries an immutable exclusion warning and no
  wagering-approval claim; the original scan remains failed in its own
  `scan_run` audit record.

Any additional provider, identity, sport, coverage, or model error still
blocks publication. A current-day MLB game also blocks recovery.

**Activation checklist:** inspect the day's actual eligible slate and source
errors in the authorized runtime, confirm model and market rows for the
other sports, test the scoped artifact and Discord publication in staging,
then explicitly approve an audited isolated rollout with rollback.
Neither this development branch nor CI automatically enables the flag.

## Explicit private-channel delivery test tool (never runs automatically)

A new helper `tools/verify_discord_delivery.py` uses the existing bot identity
and an explicitly configured private `JABBAZI_DISCORD_DELIVERY_TEST_CHANNEL_ID`.

- `python tools/verify_discord_delivery.py` only validates ownership, guild,
  privacy, bot visibility and send permission. No message is sent.
- `JABBAZI_DISCORD_TEST_SEND_APPROVED=true python tools/verify_discord_delivery.py --send-test`
  sends **one clearly labeled diagnostic message**, with all mentions disabled,
  only after private-channel preflight passes. Set the test channel ID to a real,
  explicitly authorized, private non-picks destination before running.
- On actual success it prints `DELIVERED` with a Discord message ID and UTC time.
  Non-2xx responses, missing acknowledgement, unknown permissions and unsafe
  destinations fail closed. The CLI never prints tokens, raw Discord error
  bodies, or messages from members.
- This command is **not executed by GitHub CI, Render deployments, or this
  development change**. Operator activation and observed delivery evidence are
  still required; never claim a live delivery based on synthetic tests alone.

## Authorized staging/production acceptance steps

1. Run `python tools/verify_jabbazi_discord.py` in an **authorized existing Render runtime** that holds the bot token. Do not print, copy, or export the token. Inspect `CHANNEL_UNAVAILABLE_OR_STALE:status` and `CHANNEL_UNAVAILABLE_OR_STALE:sheets` outcomes, then verify current intended channel IDs and bot View/Send/Attach/Embed permissions in Discord. Do **not** choose an arbitrary replacement channel or loosen private VIP permissions.
2. Investigate the 09:00 daily source scan failures from the existing worker/database logs and safe `DISCORD_DAILY_SCAN_AUDIT` records. Resolve source availability and quota/identity failures. Verify a healthy frozen same-day sheet is created and content remains scoped to today's eligible slate.
3. Verify the dedicated sheet channel using a **clearly marked test message in an authorized private test channel**, with explicit operator approval, and record the returned message ID. Then verify a scheduled daily cheat sheet is delivered once and that the VIP app presents the same immutable snapshot. Avoid posting a test to a public or real-picks channel.
4. Confirm separate NBA, NFL, and NHL provider entitlement, complete eligible-slate coverage, exact-line/player matching, and timestamp/freshness audits. Mock/sampled endpoint calls are not release acceptance. Preserve `RESEARCH_ONLY` and `VALIDATING` for unapproved models.
5. Test full CI, browser, container, permissions, idempotency, and delivery logs on the exact change commit. Review PR and obtain deployment authorization, then deploy only verified fixes to the **existing** services with rollback evidence.

**Out of scope for this safety hotfix:** replacing the existing 09:00 game slate scheduler with a new 08:30 scan / 11:00 PM preview orchestration, migrating unmerged V6/V7 paid research, changing Discord roles, or promoting joint NBA/NHL model probabilities. These require separate acceptance and operator review. PR #80, Issue #79 and PR #90 release gates remain blocking.

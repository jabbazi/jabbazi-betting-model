# Private JABBAZI Scanner GPT

**Connection verified September 23, 2026:** the saved GPT is live with **Only me**
access. A real `Scan everything` prompt completed against the cloud and returned
fitted NFL/MLB research probabilities. This verifies integration, not betting
approval, model profitability or full sport/prop coverage.

Owner entry point: https://chatgpt.com/g/g-6ab35da167c08191b6007d59a75b497f-jabbazi-scanner

The deployment exposes a **GPT Action**, not an automatically installed ChatGPT
app. A normal conversation, including one named Scanner, cannot execute this API
until it uses the configured custom GPT. No OpenAI API subscription/key is needed
by the server. GPT creation/action availability depends on the owner's ChatGPT account.

Setup: https://jabbazi-research-api.onrender.com/chatgpt

Import: https://jabbazi-research-api.onrender.com/chatgpt/openapi.json

The schema contains only `scanEverything`, `getScanResults`, and
`getScannerModelStatus`. Authentication is API Key / Bearer. Save the GPT as
**Only me**. This is a single-owner integration: anyone permitted to use a shared
GPT would also use its stored action key, so do not share or publish this GPT.
Discord roles do not grant scanner access.

## Authentication and revocation

The owner-only setup endpoint derives a separate HMAC-SHA256 credential from the
existing service secret, a fixed scope label and `JABBAZI_CHATGPT_TOKEN_VERSION`
(default `1`). It never returns the owner credential. The scoped key cannot use
the ledger API, general scan API, owner settings or publishing functions. The
owner credential itself is not accepted as the scoped action key. Secrets remain
in memory on the setup page and are copied only by an explicit button action.

Change `JABBAZI_CHATGPT_TOKEN_VERSION` and redeploy the API to revoke the old key
without changing the owner's existing API credential. Set
`JABBAZI_CHATGPT_ENABLED=false` to disable the entire bridge. Rotating the service
secret also revokes the action key. Do not commit either credential or put them in
GPT instructions, query strings, chats, logs or screenshots.

## Execution contract

- POST a new UUID `request_id` once to `/v1/chatgpt/scans`.
- The HTTP response returns promptly with a persisted scan ID. A background task
  invokes the same scanner/model registry as the owner API, full mode, with a
  server-controlled 15-credit budget and 50-credit reserve. Existing monthly
  quota checks and cross-service scanner lease also apply.
- GET `/v1/chatgpt/scans/{scan_id}?page=1` for status/results. Poll at the indicated
  interval, never repeatedly start jobs. Pending reads now wait up to ten seconds
  on the server so a GPT cannot burn its polling allowance in an immediate loop.
  Completed, expired and missing results return immediately. Reads never launch
  another provider scan. Idempotent retries return the original
  job without additional provider calls. New jobs have a 120-second cooldown and
  are rejected while a previous job is in progress (up to ten minutes).
- Requests and results are append-only evidence in PostgreSQL. No new tables or
  paid services are required. Background execution lives in the API process; it
  is not a durable job queue. Interrupted jobs expire after ten minutes and are
  **not automatically retried**. Owner must explicitly start another scan.
- Results are paginated 25 rows at a time, up to 260 archived action rows; total
  actions and truncation remain visible. `page_action_count` is this page only;
  `total_returned_actions` and model coverage span all `total_pages`. Quote timestamps are rechecked on every
  read. Anything older than 120 seconds or already in play is marked STALE DATA.
- Chat results prioritize rows with a fitted model probability and model version
  before applying the 260-row cap (`result_ordering=model_coverage_first`). This
  is a coverage order, **not a bet ranking**. Model coverage reports both full-scan
  and returned-row counts, so a truncated response cannot imply every estimate
  was returned. The existing general scan API retains market-relative ordering.
- Probabilities, model versions, uncertainty and probability edge come directly
  from the shared model registry/scanner. Market consensus remains a separate
  field. Shadow estimates do not receive actionable ROI, stakes or playable prices.
- All returned rows are research-only (WATCH or STALE DATA), even if a future
  core scanner can produce a different state. No stake or playable price is
  advertised. No probabilities are substituted for missing model estimates.
- Full scan means active supported feeds within the budget, NFL/MLB/CFB first;
  it does not mean every league, prop, derivative, or model is implemented.

## Acceptance checks

1. Import schema in the private GPT; configure bearer authentication.
2. Test model status; confirm the known NFL and MLB research model versions.
3. Ask `scan everything`; verify an actual action call, UUID and returned data.
4. Duplicate the request ID and verify no extra scan is queued.
5. Check omitted/invalid credentials return 401 and admin routes reject the
   scoped key. Expired results must not be presented as current prices.
6. Confirm GPT sharing is Only me; no Discord publication occurred.

Server unit/integration tests use mocked provider responses. A successful server
deployment is not proof that the owner's ChatGPT account has been connected.

## Verification on September 23, 2026

- Application commit `845b02d02980f81a3bb077f5799f7c3f3ba60c13`: 173 local tests
  passed, unused/import checks passed, GitHub workflow `35818104609` succeeded.
- Existing Render API deployed successfully in 52.3 seconds. Public health,
  database readiness and action schema returned 200; unauthenticated scoped
  model-status returned 401. Worker did not need a restart for this API change.
- Authenticated HTTP verification from the live API container returned the NFL
  and MLB shadow versions and CFB UNAVAILABLE. The scoped key was rejected by
  the owner review endpoint (401).
- Real action job `290187a5-ab43-4679-b5bc-a661328d11ff` started at
  `2026-09-23T04:25:37.692869+00:00`, completed at
  `2026-09-23T04:26:16.716982+00:00`: 5 feeds, 3,512 archived quotes,
  1,346 total actions including 198 model-backed research actions, no errors.
  The result explicitly reports its 260-row response/archive limit and
  `truncated=true`, with 25 rows per page. Betting remains disabled.
- ChatGPT was logged out in the connected browser. The custom GPT still needs
  authenticated setup/import, a private action key, Only me sharing, and an
  actual prompt-to-action test. The phrase is **not yet connected in chat**.

Official references (checked September 23, 2026):
- https://developers.openai.com/api/docs/actions/getting-started
- https://developers.openai.com/api/docs/actions/authentication
- https://developers.openai.com/api/docs/actions/production

## Model-probability connection follow-up

- A read-only check of all 11 pages of the earlier live job confirmed actual
  NFL/MLB probabilities and model versions reached the action response. However,
  market-only ordering retained just 66 of 198 modeled rows within the 260-row
  cap (36 NFL, 30 MLB; only five modeled rows on page one).
- Commit `cfd9a01d141a5e93c21f6bacadc20b28c3fed9a6` corrects that response
  selection with model-coverage-first ordering, without changing model inference,
  risk approval, the provider budget or the general API's ordering.
- 175 local tests passed; GitHub workflow `35819898842` succeeded. New regression
  tests run the real fitted NFL and MLB artifacts through registry, inference,
  scanner, shared API, stored job and chat presentation, with mocked provider
  responses. Each verifies the modeled row survives 270 higher-ranked
  market-only rows and retains its exact probability, version and uncertainty.
- The existing Render API deployed this commit successfully in 45.5 seconds.
  The worker/model refresh did not require a restart. Scoped credentials still
  receive 401 from the owner review API.
- Fresh authenticated action job `94d50ac4-59ff-48ec-8419-aa72e439ac8a`
  started at `2026-09-23T04:52:20.658861+00:00` and completed at
  `2026-09-23T04:52:56.807419+00:00`: five feeds, 3,458 quotes, 1,318 total
  actions, 200 modeled actions, all 200 retained in the 260-row response;
  page one contained 25 modeled rows. Both fitted NFL/MLB versions were present,
  errors were empty, and betting remained disabled. No wagers or Discord posts.
- This proves the live backend connection, **not** the unfinished ChatGPT
  account/GPT configuration or profitable out-of-sample performance.

## GPT editor setup follow-up

- Signed-in ChatGPT access was verified and a new `JABBAZI Scanner` draft was
  prepared with the private scanner instructions and three scoped actions.
- The actual GPT editor rejected the generic model-status response schema
  (`object schema missing properties`). Replacing it with explicit
  `ScannerModelStatus`/`ScannerModelState` response models removed the editor
  error; all three actions appeared. Local verification: 176 tests passed and
  unused/import checks passed.
- Authentication, private publication and prompt-to-action verification are
  still pending. Preparing the draft is not evidence of a working connection.
- ChatGPT's displayed notice says GPTs retire on December 11. This currently
  supported private GPT path needs migration to a plugin before that deadline;
  the existing action API is not an authenticated MCP plugin.

## First authenticated GPT scan and fixes

- After owner-provided secure key entry, the actual GPT preview retrieved the
  deployed NFL/MLB versions, SHADOW_ONLY status and NCAAF UNAVAILABLE.
- The preview's scan action created `c10b5a6d-9e29-4e70-a5c4-c85dfdbb7b84`.
  Its completed result was retrieved in a follow-up prompt and independently
  checked against PostgreSQL: generated `2026-09-23T05:29:26.787862+00:00`,
  five feeds, 3,400 quotes, 1,322 candidates, 206 modeled candidates, 260
  stored rows across eleven pages. Page one contained 25 rows, including
  actual NFL and MLB fitted probabilities. Betting remained disabled.
- The GPT ended the initial turn before the job completed, then incorrectly
  described all 260 stored rows as page one. This is an observed presentation
  defect, not a missing model integration. Added bounded ten-second server
  waits, explicit per-page counts and stricter paging/provenance instructions.
- Regression checks cover early completion, bounded pending waits, no extra
  scan execution, and immediate complete/expired/missing results. Local suite:
  181 tests passed; unused/import checks passed. Private publication and a
  final prompt test after deploying these fixes are still pending.

## Saved private GPT acceptance result

- Deployed `3b48f3817e60a6392bf32dd49bae740529300de2` to the existing Render API;
  deployment succeeded in 51.2 seconds. GitHub verification run `35822979639`
  succeeded, including tests, container stack checks and backup/restore checks.
- Saved GPT `g-6ab35da167c08191b6007d59a75b497f` with the corrected schema,
  instructions and owner-provided scoped credential. The editor displayed
  `Live` and `Only me` and confirmed `Settings Saved`.
- In the saved GPT, the exact prompt `Scan everything` completed in one turn
  (UI displayed 1m 3s). It created job
  `4e5a0e40-f237-4b96-9a14-70012992e968`, generated
  `2026-09-23T05:39:49.871495+00:00`: five feeds, 3,400 archived quotes,
  1,324 candidates, 206 modeled candidates, 1,118 unmodeled candidates,
  260 stored rows across eleven pages, no errors, betting disabled.
- The GPT accurately said it fetched only page one and showed a sample rather
  than claiming the entire 260-row archive was one page. Independent read-only
  PostgreSQL verification confirmed page one had 25 rows and the five checked
  NFL/MLB probability examples matched the stored rows at displayed precision.
- Output retained SHADOW_ONLY/WATCH, identified stale prices, left expected ROI
  unavailable, and reported CFB and prop/TD model gaps. No wager or Discord
  publishing action is exposed by this GPT.
- Regular ChatGPT conversations remain unconnected unless they use this GPT.
  ChatGPT currently displays a December 11 GPT-to-plugin migration deadline.

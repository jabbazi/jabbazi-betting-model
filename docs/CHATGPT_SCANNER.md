# Private JABBAZI Scanner GPT

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
  interval, never repeatedly start jobs. Idempotent retries return the original
  job without additional provider calls. New jobs have a 120-second cooldown and
  are rejected while a previous job is in progress (up to ten minutes).
- Requests and results are append-only evidence in PostgreSQL. No new tables or
  paid services are required. Background execution lives in the API process; it
  is not a durable job queue. Interrupted jobs expire after ten minutes and are
  **not automatically retried**. Owner must explicitly start another scan.
- Results are paginated 25 rows at a time, up to 260 archived action rows; total
  actions and truncation remain visible. Quote timestamps are rechecked on every
  read. Anything older than 120 seconds or already in play is marked STALE DATA.
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

Official references (checked September 23, 2026):
- https://developers.openai.com/api/docs/actions/getting-started
- https://developers.openai.com/api/docs/actions/authentication
- https://developers.openai.com/api/docs/actions/production

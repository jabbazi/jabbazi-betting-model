# JABBAZI private plugin connection

Prepared September 23, 2026 for the owner's regular ChatGPT scanner workflow.
The existing private GPT Action remains supported. This adds a separate OAuth
MCP connection; a prompt or memory alone does not connect an existing chat.

## Connection contract

- HTTPS MCP endpoint: `https://jabbazi-research-api.onrender.com/mcp`.
- OAuth client ID: `jabbazi-chatgpt` (predefined public client; no client secret).
- Exact redirect URI: `https://chatgpt.com/connector_platform_oauth_redirect`.
- Resource/audience: `https://jabbazi-research-api.onrender.com/mcp`.
- Scope: `scanner:research`. No owner/admin/ledger/Discord capability.
- Tools: `scan_everything`, `get_scan_results`, `get_model_status`.
- Private owner consent uses the existing **scoped scanner key**, entered directly
  on the JABBAZI consent page. Do not enter the owner API token or provider key.
- Authorization code + S256 PKCE, fixed client/redirect/audience/scope validation,
  issuer identification, five-minute single-use codes and CSRF-bound consent.
- Access credentials last one hour. Refresh credentials rotate and cannot extend
  the original 30-day authorization. Reuse of a consumed refresh revokes its
  authorization family. Only credential hashes are persisted in PostgreSQL.
- Revoke all plugin grants by incrementing `JABBAZI_MCP_TOKEN_VERSION` and
  redeploying the API. Disable via `JABBAZI_MCP_ENABLED=false`. Existing global
  scanner disable and key rotation also revoke this connection.
- MCP tool discovery requires authentication. Unsupported origins/methods, malformed
  requests, oversized bodies and unrecognized credentials are rejected.
- Consent attempts are limited to 10 per ten minutes per observed client-address
  hash, shared through PostgreSQL. Reverse-proxy address behavior needs live
  verification; a shared proxy may impose an overly conservative shared limit.

The transport is stateless Streamable HTTP with JSON responses; no server-push
stream or session ID is needed. The adapter delegates to the same job and
presentation functions as the private GPT, preserving 15-credit scan budgets,
120-second cooldown, idempotent request UUIDs, pagination and SHADOW_ONLY output.
It does not retrain, approve models, change the worker, consume provider credits
on a status read, or create new paid services. Scan jobs remain API-process
background tasks, not a durable queue.

## Account setup after deploying the API

1. In ChatGPT, enable Developer mode under Settings > Security and login.
   This is a security-sensitive account setting and requires the owner's consent.
2. Add a private MCP connection in Plugins, using the endpoint above, OAuth and
   the predefined client ID. Leave client secret blank.
3. Check that the displayed callback is the exact allowlisted redirect above.
   If it differs, stop and review configuration; do not weaken callback validation.
4. Complete the JABBAZI consent page with the private scanner key, securely.
5. Enable/install the private connection and select it in the owner's scanner
   chat. Availability in an existing thread/mobile client must be tested, not
   inferred from successful server deployment.
6. Test model status first without consuming provider credits, then one explicit
   `scan everything`. Verify the returned scan ID, model versions and actual
   probabilities. Reuse the scan ID while polling; do not start repeated jobs.
7. Keep the integration private. The scanner is not a Discord member feature.

Tool descriptions specify the `scan everything` trigger and result provenance.
A private routing plugin is now packaged under `integrations/jabbazi-scanner`.
Its MCP configuration uses the real deployed endpoint; it does not invent an
app/connector ID. Its routing skill requires actual connected tools and explicitly
reports missing access. Never claim that a chat is connected before a real
successful tool call in that chat.

## Private plugin created September 23, 2026

- Name: `jabbazi-scanner` (display name JABBAZI Scanner), version `0.1.0`.
- Plugin ID: `plugins_6ab3f91ced948191a311a57e86f73def`.
- Release ID: `pluginrel_6ab3f91dd4148191843a9120f47d986d`.
- Creator result: `created`; visibility: private; included skill: `scan-everything`.
- https://chatgpt.com/plugins/plugins_6ab3f91ced948191a311a57e86f73def

The plugin page was opened and displayed the private package, MCP URL, routing
skill and an Open in desktop app action. This is not proof of authorization in
regular ChatGPT or on the owner's phone. Developer mode remained off. Native
custom-connector creation, secure OAuth consent and an actual regular-chat tool
test are still pending. No owner/provider/scanner credentials were put in the
plugin package.

## Verification record

- Local OAuth/security checks cover redirect/client/audience/scope restrictions,
  PKCE, CSRF, consent throttling, single-use codes, refresh rotation/replay,
  expiry, revocation, credential hashing and owner-API isolation.
- Scanner integration checks cover job idempotence, duplicate-charge prevention,
  model probability versus market probability, pagination and stale-price guards.
- Official Python MCP client 2.2.0 is a **dev/test dependency only**; it verifies
  initialization, tool discovery and an authenticated model-status call through
  the real shared model registry. No new production dependency is needed.
- Local full suite: **203 passed**; Ruff undefined/unused-name checks passed.
  API commit `97a398e` was deployed on Render and confirmed live on September
  23, 2026 (successful migration, startup and readiness checks). OAuth account
  connection and a successful regular-chat tool call remain pending.

Official references checked September 23, 2026:
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/plugins/deploy/connect-chatgpt
- https://learn.chatgpt.com/docs/build-skills

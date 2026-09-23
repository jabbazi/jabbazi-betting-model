# JABBAZI hardening and model-readiness audit — 2026-09-23

## Scope and verified local work

This is a focused hardening pass on the existing platform, not completion of all
sports or a claim of continuous overnight coding. Baseline is remote commit
`5e2e35b007a93cba4ac4e8d3b3aeb741f1dba92d` on `build/production-foundations`.

- Fixed member price freshness: both JSON and image routes check the current time,
  not only the scan timestamp. Quotes expire after 120 seconds or at kickoff.
- Member images always use the best-supported-edge filter, including legacy URLs
  with `featured=false`. Unmodeled props cannot appear as invented model edges.
- Browser clears old rows on failed refresh, sport/tab change and logout, removes
  prices as they expire, and hides data when the research session expires. A
  server-anchored clock prevents a backward device clock from extending validity.
- Added scope, guild and expiry checks for member tickets/sessions. Member access
  remains separate from owner/scanner credentials. Existing sessions last at most
  15 minutes; instant role-removal revocation is not implemented.
- The app defaults to conservative-value ranking, not the highest hit probability.
  Its main columns remain Model / Market / Edge. It is experimental research,
  not an official main card. Discord archive coverage remains separate.
- Added a reproducible saved-artifact audit: `python tools/audit_model_readiness.py`.
  It does not refit or promote a model and checks report/artifact provenance.
- Added provider-neutral prop-dataset admission checks for initial MLB pitcher K
  and NFL passing/rushing/receiving yards research. It rejects scrambled data,
  future features, labels crossing chronological split boundaries, inconsistent
  features, duplicate player/game rows and unresolved outcomes. DNP/void records
  are excluded and counted, not turned into zero performances. This is **not a
  trained player-prop model**. Supplied rights/timestamp declarations still need
  independent review. A 100-row split floor is not proof of statistical power.

Local verification: **261 pytest tests passed**, including four Node-based browser
logic checks via the pytest wrapper; Ruff undefined/unused-name checks passed.
The Node harness is a simulated DOM, not a replacement for a live browser check.
One known dependency warning concerns discord.py's deprecated `audioop` import.
Cloud rollout evidence must be recorded separately after actual verification.

## Audit result: do not promote models

| Saved moneyline diagnostic | NFL | MLB |
|---|---:|---:|
| Sample | 284 decisive games | 2,473 games |
| Brier (lower is better) | 0.223282 | 0.247026 |
| Log loss (lower is better) | 0.635409 | 0.687039 |
| Bucket-weighted calibration gap | 0.050201 | 0.034459 |
| Paired market sample | 284 | 0 |
| Model Brier minus market | +0.012376 (worse) | unavailable |

These are existing 2025 diagnostics, already inspected, not a new untouched test.
The calibration gaps are descriptive, not confidence intervals. Existing score
models are based on team score/rest/home-field features; they do not yet have
verified QB, pitcher, lineup, usage or weather feature coverage. The 8% relative
probability haircut is a policy choice, not estimated uncertainty. NFL does not
beat its paired market baseline here. MLB lacks paired historical odds. Neither
has decision-time-verified execution/ROI/CLV evidence. `SHADOW_ONLY` and disabled
betting remain in place. NBA, tennis and CFB do not gain trained models in this pass.

## Data and owner actions, consolidated

1. **ChatGPT owner connection:** enable the private MCP connection only with
   informed owner authorization. Official flow uses Settings > Security and login
   > Developer mode, then a private MCP app/connection, depending on workspace
   availability. Backend: `https://jabbazi-research-api.onrender.com/mcp`.
   Public client ID: `jabbazi-chatgpt`; no client secret. The scanner credential
   belongs only in the private consent form, never chat, GitHub or Discord.
   Existing plugin: `https://chatgpt.com/plugins/plugins_6ab3f91ced948191a311a57e86f73def`.
   A real authorized tool call is required before claiming ordinary chat works.
2. **Historical odds entitlement and quota:** confirm current provider account
   access before any historical download or quota increase. The Odds API paid
   history includes event-level player props from May 2023 with snapshot-based
   billing. Current-odds success does not prove historical entitlement. No new
   subscription, credits or scan frequency increase was purchased/approved here.
3. **Stats and usage rights:** provide a licensed real-data source covering MLB
   player logs, starting pitchers/lineups and NFL player logs, snaps/usage,
   injuries/depth charts, plus historical availability timestamps. SportsDataIO
   is a candidate, not installed/licensed here. Its commercial agreement must
   cover modeling and derived-output display. Its free trial uses scrambled data;
   Discovery Lab is personal/noncommercial. Neither substitutes for this paid app's
   required commercial real-data agreement. Obtain a scoped quote before purchase.
   Effort: material provider mapping, point-in-time storage, identity reconciliation
   and validation; not merely pasting a key. An equivalent licensed provider is fine.
4. **Display rights:** The Odds API's published terms permit commercial analytical
   displays, derived values and ML training, while prohibiting raw-feed resale.
   JABBAZI must remain analysis rather than a repackaged feed. This does not grant
   rights to unrelated statistics providers, photos, Outlier feeds or other cappers'
   paid content. Obtain provider clarification where the intended usage is unclear.
5. **Prospective validation:** predeclare features/splits and acceptance gates,
   fit/calibrate on permitted point-in-time data, then log an untouched forward
   sample with actual offered/closing prices and full losing/no-bet records.
   Validate probability metrics and calibration alongside ROI/CLV/drawdown. No
   promise of profitability or time-to-edge follows from adding a subscription.

No new login, data-provider subscription or cloud service was created by the local
work. GamblyBot installation and main-card/sprinkles channel creation were verified
in the preceding change, not newly repeated. Outlier is an external account link,
not a licensed automated feed. No wagers or public betting recommendations were made.

## Official references checked 2026-09-23

- ChatGPT MCP connection: https://developers.openai.com/plugins/deploy/connect-chatgpt
- Odds history: https://the-odds-api.com/historical-odds-data/
- Odds usage terms: https://the-odds-api.com/terms-and-conditions.html
- SportsDataIO data rights: https://sportsdata.io/help/data-rights-and-licensing-questions
- SportsDataIO products/trial limitations: https://sportsdata.io/developers

## Remaining engineering after data approval

Fit and backtest the narrow prop targets first; add TD-specific usage/TD-allocation
models separately. Add point-in-time feature provenance checks, prediction coverage
monitoring, paired market benchmarks and prospective CLV capture before broader
markets. Make any eventual BET NOW promotion an explicit reviewed decision, never
an automatic result of obtaining a provider key or passing software unit tests.

## Verified rollout

Application commit `16c17c0d1757639f577f7cf0cc04cd2ea65d5ddc` passed GitHub
workflow runs `35906678004` and `35906670124`. The PostgreSQL-enabled CI suite
reported **275 tests passed**, plus authenticated HTTP smoke, Docker startup,
database backup/restore and database-outage checks. Local 261-test runs omit the
PostgreSQL-specific collection; these counts are deliberately distinguished.

- API deployment `dep-daq25ht9fdbs73eke6ug`: succeeded/live, 2026-09-23 19:05:31 UTC.
- Worker deployment `dep-daq25n9srm7s73dabmt0`: succeeded/live, 19:05:50 UTC.
- API readiness logs returned 200 after rollout. The live member app reload
  displayed server branding and required a fresh private `!vip` link, with no
  protected research data displayed to the signed-out browser.
- The latest observed scan before the new rollout recorded 3,952 quotes and 232
  model-backed research actions with both NFL/MLB versions and no scan errors.
  This is prior-worker evidence, not proof of a newly requested scan or prop model.
- No fresh authenticated member session or regular-ChatGPT tool call was completed
  during this rollout check. Protected paths have automated integration coverage;
  do not describe that as a new live member/ChatGPT end-to-end authorization.

These changes did not increase quote quotas, change model coefficients, enable
betting, place wagers, or purchase a provider. The code, tests and this handoff are
committed to the existing development branch; no claim of perfection is made.

# VIP production runbook

## Deploy and rollback

Production branch: `build/production-foundations`. Run unit/integration tests, lint, UI browser checks and CI container/database restoration tests. Merge green code only. Deploy the existing API first, then worker; both share the database. Do not provision services or change paid plans for this release.

Verify `/readyz`, `/vip`, static assets, anonymous protected-route rejection, worker gateway startup and `VIP_ACCEPTANCE_VERIFICATION`. The read-only probe verifies the configured owner's Discord membership, creates a short-lived ticket, exercises protected reads, verifies ticket replay rejection, and logs out. It prints only route status/counts and stores a safe report. No credentials are printed and no test bets or alerts are published. It does not replace a human mobile `/vip` interaction test.

For rollback, deploy the prior known-good commit to API and worker. Append-only data is backwards compatible. Do not reset the database or edit settled records. After rollback, verify the previous portal and gateway. Keep backup metadata before operational changes.

## Incidents

| Incident | First response | Recovery verification |
|---|---|---|
| Provider outage / stale odds | Keep PRICE CHECK / UNAVAILABLE; optionally pause publication | fresh timestamp, healthy source, no stale BET NOW |
| Model anomaly / bad input | Admin pauses affected sport publication with reason | audit record; app quarantined; new Main Card posts blocked |
| Incorrect lineup / injury | Pause affected publication; inspect canonical provider/model evidence | verified source correction; never invent context in UI |
| Discord role service outage | API fails closed when 30-second cache expires | fresh current role check succeeds before access resumes |
| Discord gateway outage | Inspect safe worker error codes; restart once root cause fixed | gateway ready and four registered slash commands |
| App/API outage | Check readiness, DB, deploy health, safe VIP_REQUEST_FAILED codes | unauthenticated rejection + authenticated probe |
| Database outage | No fallback fabricated content | readiness restored; ledger and snapshots readable |
| Bad morning publication | Preserve original frozen record; publish a separately labeled correction through existing authorized operations | original timestamp/history remain intact |
| Notification spam | Disable member in-app notifications; inspect event IDs/claims | repeat evaluation creates no duplicate alert |
| Rollback | Redeploy known-good image/commit, preserve DB | readiness and guarded portal access |
| Restore | Restore backup to isolated database first, validate schema/events/ledger counts and immutability | run existing `tools/verify_ci_restore.py` process before controlled promotion |

Automated backup/restore testing already runs in the existing disposable Postgres CI stack. This is **not proof of a restored production backup**. Production retention/export configuration must be verified in Render before claiming disaster-recovery completion. Never expose database connection strings in logs or the browser.

Admin access requires the existing server owner or configured admin role IDs. No password or separate admin secret is added. Use a fresh `/vip` link and open More → Operations. DEVELOPER cannot change operations. Never run destructive override tests against production; integration tests use isolated SQLite/Postgres.

## Feature status and roadmap

COMPLETE in code/test scope: private Discord-ticket access, bounded live-role revocation, shared-data terminal, mobile navigation, sports projection, current research/detail, shared frozen moneyline sheets/history, current search aliases, private settings/watchlist/inbox, authentic official performance summaries, model-center metadata, safe publishing pause/audit, PWA metadata/static-only cache, profit-boost calculator.

PARTIAL: home personalization currently prioritizes selected sports; books/teams preferences are stored but do not yet prioritize every view. Game/player context is current-event research, not a full career/usage profile. Existing official cards deep-link; automatic invalidation edits across already-posted Discord cards are not built. Initial/current moneyline comparison exists; full multi-market and final/pregame versions do not. Optional bankroll storage exists; per-user exposure and drawdown tracking do not. Model evaluation summary exists; interactive calibration plots do not.

BLOCKED by evidence/readiness: production Top 10 contents where player models remain validating/shadow; official plays where existing cash gates remain disabled; current prices between scheduled scans; missing lineup/weather/goalie context; authentic CLV/graded performance where the ledger lacks matching trusted evidence. No model promotion or extra provider spending is authorized by a desire to fill the UI.

PLANNED: correlated 2–4 leg/SGP builder, richer promo types, full current-player/team centers, fuzzy historical result search, browser push, personalized FREE accounts, production backup restoration drill, native apps, external analytics. No usage analytics SDK is installed. Prioritize data completeness and independent model validation before these features.

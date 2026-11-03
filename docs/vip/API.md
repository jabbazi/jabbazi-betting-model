# VIP API and developer handoff

All `/v1/vip/*` routes require the secure member cookie and current Discord entitlement. POST/PUT/DELETE additionally require Origin matching `JABBAZI_MEMBER_ORIGIN`. JSON responses include `Cache-Control: no-store`. Session exchange and logout remain under `/v1/member/`. API routes never mint tickets. Only the Discord bot or the explicitly scoped owner acceptance probe can do so after verified membership.

| Method / path | Contract |
|---|---|
| GET me | tier, features, session expiry, private preferences, server time |
| GET home | observed sport activity, six research rows, current official card, morning-sheet availability |
| GET board | sport/query/market/status/sort, 50-row offset pagination, source timestamp |
| GET search | bounded search of current shared snapshot, aliases, grouped player/event context, navigation |
| GET detail/{id} | provenance, fair price/EV, observed books, same-event and alternate rows |
| GET picks | same official gate and record IDs used by Discord |
| GET sheets?day=YYYY-MM-DD&sport=MLB | immutable morning publication, original timestamp/prices |
| GET archive | metadata for 90 most recent sheet publications |
| GET changes | moneyline price/model changes against today's frozen morning baseline |
| GET top10?kind=hr/td/nba_props/nhl_goals | up to ten qualified rows; empty when validation/freshness gates fail |
| PUT preferences | validated unit_size, optional bankroll, sports/books/teams, in-app alert opt-in |
| GET/POST watchlist | member-only watch state; candidate_id and optional minimum_decimal |
| DELETE watchlist/{id} | remove from the authenticated member's list |
| GET performance | authentic scanner-origin ledger periods/groups, explicit provenance |
| GET models | shared registry versions, stages and evaluation summaries |
| POST promo | decimal odds + profit boost + optional user probability; informational calculations |
| GET admin | ADMIN only: safe audit and current publication flags |
| POST admin/control | ADMIN only: allowlisted pause flag, boolean value, required reason |

Error semantics: 401 missing/expired session; 403 revoked role or missing admin privilege/Origin; 404 candidate no longer in current snapshot; 422 invalid input; 429 rate cap; 503 unavailable role verification or backend. Do not retry mutations automatically after ambiguous network errors.

Search is an in-process bounded projection of at most 10,000 rows in one indexed latest-snapshot record. No additional infrastructure. It supports common aliases, all terms matching and current-first ordering; it is not a comprehensive historical player database, typo-correcting engine or full-text results index. Historical sheets are a separate archive. Team and player context use the same event/participant data as current research.

Deep links: `/vip#detail=<candidate-record-id>` for official Discord cards; app research uses deterministic opportunity IDs. A valid session is required. Deep-link continuation through a separately requested Discord sign-in link is not yet persisted. Never attach a member access token to a public alert URL.

Data contracts intentionally omit provider response bodies, feature vectors, credentials and other members' settings. Research probabilities and estimated EV can come from non-production models only when marked research-only; Top 10 requires production-approved player stage. No inferred win/loss, unavailable play-to price, missing weather or injury context is fabricated.

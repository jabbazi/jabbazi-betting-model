# Implementation audit — September 22, 2026

**The master specification is not complete. No production betting model, cloud
deployment, or paid Discord service is verified.** This change establishes tested
research infrastructure and makes the outstanding work explicit.

## Inspected starting state

- `jabbazi/jabbazi-betting-model` contained only a README when its actual tree was
  fetched. Earlier repository metadata reported size 0; that did not establish
  that the repository was empty. The existing main commit is preserved.
- Source was recovered from the earlier MLB shadow artifact and the subsequent
  three-sport starter. Functioning odds ingestion, Decimal math, SQLite records,
  market shopping, MLB trainer, API, and tests were preserved.
- The starter had 45 passing tests, real MLB/NFL moneyline research artifacts,
  a CFB history adapter/trainer without a real trained CFB artifact, Discord setup
  and private review delivery, and Docker templates.
- PostgreSQL previously existed as an unused SQL template; there was no functioning
  production database integration. That template is archived, not run as a migration.
- No configured live odds, CFBD, Discord, or cloud credentials were available.
  Railway was not connected. No provider purchase or cloud provisioning was performed.

## Implemented in this change

| Master scope | Current evidence | Remaining work |
|---|---|---|
| 1–2: modular platform | Preserved source plus shared domain, providers, persistence, models, research, API and worker modules | Full operational orchestration and production feature store |
| 3: betting math | Tested conversions, overround/no-vig, fair prices, edge vs ROI, push handling, play-to payout, unit conversion, joint probabilities, boost/bonus math | Line-specific CLV models and broader contract semantics |
| 4–5: ingestion | Provider abstraction, Odds API normalization, MLB/nflverse/CFBD history adapters, raw evidence archive, source/receipt timestamps | Live credentials; timestamped injuries, rosters, starters, weather and depth charts; provider contract tests |
| 6: market consensus | Complete same-book markets, freshness checks, latest-snapshot deduplication, outlier filtering, normalized consensus, two-book execution requirement | Empirical weighting and provider-specific completeness guarantees |
| 7–8: probability validation | Active registry remains shadow-only; chronological baseline evaluation; Brier/log loss/AUC/reliability/ECE and held-out isotonic framework | Actual fitted calibration, independent approval registry, rolling statistical gates and prospective evidence |
| 9: MLB | Existing moneyline code preserved; separate real-results baseline and holdout report | Starter/bullpen/lineup features and fitted run, inning, pitcher, batter and derivative models |
| 10: NFL game models | Real-results moneyline baseline, separate league tuning and neutral-site requirements | Fitted spread/total/period distributions, efficiency/QB/injury features and market superiority |
| 11: NFL props | Documented empirical/count distributions, role/usage mixtures, over/under/push pricing framework | Player feature ingestion, market-specific fitted distributions, calibration and approval |
| 12: anytime TD | Separate Poisson scoring-intensity framework; never derived from yardage alone | Fitted team TD/player scoring-share models, role updates and out-of-sample validation |
| 13: CFB | Separate trainer/adapter; LA scanner allowlist excludes player props | CFBD credential, real training, opponent adjustment and calibrated game/period models |
| 14: alternates | Exact-rung shopping and distribution-based value ranking | Automatic cross-market thesis construction and fitted derivative distributions |
| 15–16: parlays/correlation | Shared-scenario joint probabilities, pairwise diagnostics, actual payout/freshness pricing, tagged portfolio limits | Fitted SGP dependence, live SGP payouts, multi-event exposure mapping, validated candidate generation |
| 17: promos | Profit boost, capped incremental-profit, and stake-not-returned bonus math | Verified eligibility/expiry/max-stake records and provider integration |
| 18–19: decisions/play-to | Freshness/model/market/risk gates, conservative payout threshold, zero-stake suppression on unhealthy scans | Market-specific news checks, timing rules, production approvals and fuller state taxonomy |
| 20–22: bankroll/risk | One $30 unit setting; .25/.50/.75/1u tiers; fractional Kelly; daily, bet, sport, event, player, thesis, parlay and drawdown controls | Automated bankroll/settlement reconciliation and calibrated evidence-tier assignment; default scanner uses standard tier |
| 23: ledger | Transactional reservations; authenticated owner-reported wager import, settlement, history and exposure; hashes, idempotency and append-only corrections | Sportsbook reconciliation, reservation-to-placement API, full domain projections and member UI |
| 24: CLV | Scheduled pre-start snapshots, durable same-contract closing proxies, price/probability CLV endpoint | Real-feed coverage, certified closing evidence, line changes and aggregate CLV reporting |
| 25: backtesting | Timestamp-checked replay with slippage, costs, liquidity, cash overlap, drawdown, ROI, units, scores and grouped reports | Real point-in-time odds joined to features and fitted walk-forward strategies; no ROI result claimed |
| 26: health | Fail-closed database/model/freshness/feature gates, scan error suppression and lease control | Actual rolling calibration/CLV drift monitors, alert routing, operational dashboards and incident drills |
| 27: database | PostgreSQL/SQLite store, versioned migration, integration tests and disposable PostgreSQL backup/restore hash comparison | Full relational projections, restricted runtime role, host backup/restore and scale verification |
| 28: API | Authenticated scans, candidates, odds, health, owner ledger, closing proxies, CLV, operations and owner-reported performance; OpenAPI | Stable public contracts, events, member UI and independently reconciled performance |
| 29: scanner | Bounded cloud worker, leases, event-timed collector, durable monthly credit reservations, database heartbeat and delivery journal | Running host, verified live coverage, statistical drift monitoring and incident routing |
| Discord/commercial | Owner-checked setup, private channel permission checks and database-backed delivery claims/results | Real bot/server installation and permission verification, subscriptions/billing and approved paid alerts |

## Model evidence

See [MODEL_REPORT.md](MODEL_REPORT.md). The preserved MLB baseline had 2,473
decisive holdout games, Brier .244544 and log loss .681943, with no historical
odds comparison. The NFL baseline had 284 decisive holdout games, Brier .225322
and log loss .642141, worse than the paired market diagnostic. Those market
prices lack individual snapshot timestamps. CFB has no real fitted artifact.
None supports a verified profitable strategy or a paid-pick claim.

## Verification record

- Local Python 3.12: **113 tests passed**, including recovered regressions, numerical
  references, stale/outlier quarantine, API authentication/database reads, concurrent
  reservations, rollback, corrections, lease ownership, chronology, calibration,
  correlated scenarios, push handling, execution assumptions and fail-closed scanning.
- Actual local Uvicorn/HTTP smoke check passed: health 200, database readiness 200,
  authenticated stored-evidence read 200, unauthenticated read 401, and missing
  odds-provider scan 503. The service reported betting disabled.
- Static undefined/unused-name checks pass. The API test client emits upstream
  deprecation warnings; they do not change test outcomes.
- [GitHub Actions run 35784881693](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35784881693)
  passed on September 22, 2026 for source commit
  `8f4e623c1a238a8a61aa3aefe28e94ddb03da987`: **127 tests passed**, including
  14 additional PostgreSQL cases. Ruff, the actual Uvicorn/HTTP smoke, Docker build
  and container CLI passed. The disposable Docker Compose stack then ran
  PostgreSQL 17, migrations, the API and worker. Real HTTP checks verified
  authenticated owner ledger import/idempotency/settlement/history and a worker
  heartbeat with no odds credential. A separate database restore retained both
  synthetic ledger evidence hashes. Stopping PostgreSQL produced readiness and
  scan 503 responses. These tests used synthetic records and no real provider.
- `render.yaml` validated against Render's published JSON schema. The prepared
  deployment opened at Render sign-in; no account or resource was provisioned.
- Earlier uploads returned 403 because the connector was authorized but not
  installed on the GitHub account. After installation, the recovered source was
  published in [draft PR #1](https://github.com/jabbazi/jabbazi-betting-model/pull/1).
  The source tree was compared against the fetched remote with no differences.
  Existing main-branch history is preserved; the PR has not been merged.
- No live provider authentication, real Discord write, cloud deployment, billing,
  production-host backup restore, or production model approval has been verified.
  Worker/collector/delivery failures are auditable; statistical model drift alarms
  and independent host monitoring remain outstanding. A ready API does not establish
  a healthy feed, a recent worker heartbeat, or an approved model.

## Next execution order

1. Follow [GO_LIVE.md](GO_LIVE.md) to review the prepared Render resources and costs.
   Obtain account access and purchase approval before provisioning.
2. Configure host and provider secrets, apply migrations, run the research
   API/worker and verify a real odds scan with retained source timestamps.
3. Acquire permitted point-in-time historical odds/features. Establish a new untouched
   evaluation period and prospective ledger before adding model complexity.
4. Develop and compare each sport/market separately against calibrated baselines;
   fit uncertainty and calibration using separate historical windows.
5. Add prop/TD/derivative and joint-model research using real usage/injury context.
6. Complete ledger/CLV reconciliation, health monitoring and recovery exercises.
7. Verify Discord ownership, role visibility and private research delivery. Paid
   member alerts require the separate modeling and operational gates above.

## Data acquisition decisions — no purchase made

| Source | Purpose | Integration effort | Need |
|---|---|---|---|
| The Odds API | Current normalized odds; timestamped historical snapshots and close research | Live/historical adapters, snapshot jobs and shared quota reservations exist; credentials, contract tests and feature/price joins remain | Current feed essential; historical archive or equivalent essential for betting validation |
| CollegeFootballData | CFB schedules/results and available team metrics | Results adapter exists; credential, coverage checks and timestamped feature adapter remain | Required for the current CFB route; advanced fields depend on access |
| SportsDataIO | Potential injuries, depth charts, player/team stats and commercial feeds | Existing MLB results adapter only; new scoped endpoints and point-in-time schemas needed | Optional provider choice; equivalent reliable features are needed for advanced models |
| nflverse / MLB Stats API | Baseline result history and permitted research inputs | Existing adapters | Useful baseline inputs; not a substitute for timestamped odds or commercial-use rights |

Confirm coverage, historical availability, allowed redistribution and quoted pricing
with the selected provider before buying. API access alone does not establish
commercial redistribution rights for a paid Discord product.

Provider references: [Odds API v4](https://the-odds-api.com/liveapi/guides/v4/),
[sportsbook keys](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html),
[historical odds](https://the-odds-api.com/historical-odds-data/),
[CFBD keys](https://collegefootballdata.com/key),
[nflverse schedules](https://nflreadr.nflverse.com/reference/load_schedules.html).

Default odds requests include DraftKings, FanDuel, Caesars, BetMGM, BetRivers and
theScore Bet where the account/feed supplies them. The provider's documented US
theScore key is `espnbet`. Market-level timestamps take precedence; documented
book-level update times are the fallback. Missing source timestamps are rejected.

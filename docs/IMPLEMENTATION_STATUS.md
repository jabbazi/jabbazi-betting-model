# Implementation audit — September 22, 2026

**The master specification is not complete. No production betting model, cloud
deployment, or paid Discord service is verified.** This change establishes tested
research infrastructure and makes the outstanding work explicit.

## Inspected starting state

- `jabbazi/jabbazi-betting-model` was an empty public repository (size 0) when inspected.
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
| 23: ledger | Transactional reservations, lifecycle events, hashes, idempotency conflicts, append-only evidence triggers, auditable settlement corrections | User-facing wager import/placement/settlement flows; reconciliation and full domain projections |
| 24: CLV | Price/probability math, strict comparable-market closing-proxy framework | Scheduled close collection, historical close integration, durable CLV aggregation |
| 25: backtesting | Timestamp-checked replay with slippage, costs, liquidity, cash overlap, drawdown, ROI, units, scores and grouped reports | Real point-in-time odds joined to features and fitted walk-forward strategies; no ROI result claimed |
| 26: health | Fail-closed database/model/freshness/feature gates, scan error suppression and lease control | Actual rolling calibration/CLV drift monitors, alert routing, operational dashboards and incident drills |
| 27: database | SQLAlchemy PostgreSQL/SQLite store, versioned schema, migration command and database integration tests | Full relational entities/projections, runtime role provisioning, backup/restore and scale tests |
| 28: API | Authenticated scan, model status, candidates, odds, model-health history; liveness/readiness; OpenAPI | Events, portfolios, placements, CLV/performance endpoints and stable public contracts |
| 29: scanner | Bounded credit-aware daemon, configurable interval, global DB lease, health heartbeat, private delivery off by default | Running host, verified live feeds, smarter event timing, centralized delivery journal and production monitoring |
| Discord/commercial | Owner-checked role/channel setup and idempotent private research publisher preserved | Real server/bot installation, permission tests, subscriptions/billing and approved paid alerts |

## Model evidence

See [MODEL_REPORT.md](MODEL_REPORT.md). The preserved MLB baseline had 2,473
decisive holdout games, Brier .244544 and log loss .681943, with no historical
odds comparison. The NFL baseline had 284 decisive holdout games, Brier .225322
and log loss .642141, worse than the paired market diagnostic. Those market
prices lack individual snapshot timestamps. CFB has no real fitted artifact.
None supports a verified profitable strategy or a paid-pick claim.

## Verification record

- Local Python 3.12: **104 tests passed**, including recovered regressions, numerical
  references, stale/outlier quarantine, API authentication/database reads, concurrent
  reservations, rollback, corrections, lease ownership, chronology, calibration,
  correlated scenarios, push handling, execution assumptions and fail-closed scanning.
- Actual local Uvicorn/HTTP smoke check passed: health 200, database readiness 200,
  authenticated stored-evidence read 200, unauthenticated read 401, and missing
  odds-provider scan 503. The service reported betting disabled.
- Static undefined/unused-name checks pass. The API test client emits upstream
  deprecation warnings; they do not change test outcomes.
- [GitHub Actions run 35782687953](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35782687953)
  passed on September 22, 2026 for source commit
  `63775af158e6e8d688eefed6488a1f14fc292f37`: **111 tests passed** with zero
  failures, including seven additional PostgreSQL 17 storage cases; Ruff and the
  actual Uvicorn/HTTP smoke check passed. The Docker image built and its CLI ran
  successfully. The API smoke uses disposable SQLite; a full cloud Compose
  deployment and end-to-end PostgreSQL API/worker run remain unverified.
- Earlier uploads returned 403 because the connector was authorized but not
  installed on the GitHub account. After installation, all 94 source files were
  published in [draft PR #1](https://github.com/jabbazi/jabbazi-betting-model/pull/1).
  The source tree was compared against the fetched remote with no differences.
  Existing main-branch history is preserved; the PR has not been merged.
- No live provider authentication, real Discord write, cloud deployment, billing,
  backup restore, or production model approval has been verified.

## Next execution order

1. Review the published draft PR. PostgreSQL/storage and Docker CI have passed;
   the master specification remains incomplete as documented above.
2. Connect a chosen host and provider secrets, apply migrations, run the research
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
| The Odds API | Current normalized odds; timestamped historical snapshots and close research | Existing live adapter; add historical endpoints, snapshot jobs, quota accounting and joins | Current feed essential; historical archive or equivalent essential for betting validation |
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

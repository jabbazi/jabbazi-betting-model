# JABBAZI reliability upgrade — 2026-09-25

**Deployment update:** the API and worker were subsequently deployed and live-verified. See [DEPLOYMENT_VERIFICATION_2026-09-25.md](DEPLOYMENT_VERIFICATION_2026-09-25.md). The build-time status below is retained as historical context; model approval and remaining validation gaps are unchanged.

**Implemented and locally verified; not deployed. No model promoted.**
Render opens its sign-in page in this workspace. The connected live model-status tool still returns the old NFL/MLB versions and CFB UNAVAILABLE. No Discord publishing or wagering was performed.

## Diagnosis: Chiefs at Miami
Scan `8f4d0c7e-5c5c-4d7b-a0ac-2e55dc19d2c1`, generated `2026-09-25T03:20:39.916689+00:00`; game `2026-09-27T17:00:00Z`, provider event `0339a0e41bcee12820eb3e64bb5fadb4`.
The bundled artifact reproduces +2.5 = 168/285 = 58.947%, +7.5 = 212/285 = 74.386%, +10.5 = 232/285 = 81.404%, and conditional ML = 134/269 = 49.814% exactly. +11.5 is 82.105%, not the +10.5 rung.
Expected simulated score: Miami 21.754, Kansas City 21.519; Miami margin +0.235; margin SD 13.530. Six of eight equally weighted input games per team are from 2025, and two are from 2026. The six inputs are scoring form, conceding form, rest difference and home field. There is no QB/roster/injury/weather verification. The 285 paired 2024 residuals generate 16 ties (5.61%); this is another football distribution limitation, not a validated NFL tie forecast.
This is a reproducible weak/stale feature forecast, not an observed spread-sign inversion. We cannot establish the true causal personnel/news reason for market disagreement without those missing inputs. All 26 requested checks and exact input histories are in [miami-diagnostic.json](experiments/reliability-upgrade/miami-diagnostic.json). The original production feature record is not accessible through the three read-only scanner tools; the proof is an exact reproduction from the committed artifact. No probability cap was applied.
Miami main +10.5 market consensus is 49.476%, ML 15.907%. Both gaps exceed 20pp. The upgraded scanner exposes EXTREME_DISAGREEMENT plus MODEL_QUARANTINE until identity, personnel, calibration and data checks are established. Live behavior remains unchanged until rollout.

## Confirmed code defects and fixes
- Alternate spreads were keyed by absolute handicap. A +1.5/B -1.5 and A -1.5/B +1.5 could share one normalization group. A regression reproduces the Toronto/Baltimore half-mass mechanism; signed canonical-team orientation now keeps each pair separate. No exact raw September 23 provider archive was retrieved, so this proves the code defect/mechanism rather than claiming a full forensic replay of that older payload.
- `v4.2-reliability-engine` commit `4c5c52f` contains literal backslash-n sequences: Python cannot import it. The module was decoded into the real service package, with its concepts retained. Failed promotion gates no longer confer LIMITED_LIVE; frozen prospective version/bucket evidence and stability are required. Numeric defaults remain placeholders, not validated promotion policy.
- A model exception could abort the rest of a feed. Per-candidate isolation now keeps independent price research available, with explicit model errors.
- Scanner presentation omitted anomaly evidence, score distribution and input lineage. It now retains them while preserving existing tool names and request schemas.
- CLV was calculated on demand but not saved as its own evidence record. Matching-threshold comparisons now append immutable CLV evidence.

## Architecture and changes
Actual cloud path: MCP `scan_everything` → `chatgpt_api.run_background` → `api.perform_scan` → `AutomaticScanner` → `FeedPlan` / `TheOddsApiProvider` → normalized quotes → signed market pairing/no-vig/line shopping → `models.registry` → score feature generation / shared paired-score distribution → reliability/anomaly checks → candidate/forecast persistence → `get_scan_results`. `get_model_status` reads that same registry. The legacy `scanner/service.py` is explicitly disabled in production.
- One empirical joint score distribution now has a validated interface, predictive mean/variance/covariance/intervals, full ladder checks, push accounting, raw win/loss mass and shared-scenario SGP calculations. The existing paired-residual champion was already coherent; it was preserved. Conditional moneyline semantics remain separately labeled.
- NFL and CFB recency/opponent-adjusted score-form challengers use decaying historical weights and a league-prior shrinkage term. These are **not** EPA, QB or returning-production models. Recency decay alone did not beat the NFL champion.
- MLB alternatives include paired residuals, Poisson and fitted-overdispersion negative-binomial simulations (10,000 draws per evaluated game, deterministic seed). None replaced the champion.
- Platt, isotonic and beta calibration are evaluated only on subsequent held-out games. Non-monotonic fits are rejected. They are not applied independently across live score markets, which could break joint coherence.
- Pure, calibrated and market-aware fields are distinct; unavailable fields are null. The experimental shrinkage module defaults to zero model weight without matching frozen bucket evidence. It is not silently applied in the scanner.
- Owner-only diagnostics/source-pick endpoints; immutable typed source picks, lifecycle/corrections and frozen-forecast contracts; actual-dollar thesis graph and central thesis tags; promo-term validation; Bob depth helper; research-priority score explicitly unrelated to win probability. Source import, promo and Bob helpers are frameworks, not advertised as live external-data integrations.
- Identity contracts, duplicate-event detection, feature drift indicators, schema/freshness/pairing checks, missing-input reasons, model/odds snapshots and artifact hashes. Full personnel checks cannot pass without actual feeds.

## Out-of-sample diagnostics
Monthly expanding-origin 2025 evaluation. Each challenger fold separates earlier fitting labels, residual-distribution labels and probability-calibration labels, with availability gaps at boundaries. NFL/MLB 2025 was previously inspected, so this is a diagnostic comparison, not an untouched final holdout. CFB uses five seasons of archived FBS-v-FBS results (plus current state); no CFB player props.
One canonical home outcome per game/market. Spread/total tests use fixed diagnostic thresholds, not historical offered lines. NFL market quotes are retrospective reference prices with unknown observation times; no odds-feature leakage. No legitimate execution ROI or CLV backtest is available. Brier confidence intervals and hit-rate Wilson intervals are in the JSON reports.

| Sport / architecture | ML n | Brier ↓ | Log loss ↓ | ECE (5pp buckets) |
|---|---:|---:|---:|---:|
| NFL / recency_ridge | 284 | 0.227341 | 0.645321 | 0.0464 |
| NFL / recency_boosted | 284 | 0.227415 | 0.647120 | 0.0849 |
| NFL / champion | 284 | 0.223282 | 0.635409 | 0.0813 |
| MLB / recency_ridge | 2473 | 0.247857 | 0.688823 | 0.0307 |
| MLB / recency_boosted | 2473 | 0.249175 | 0.691515 | 0.0378 |
| MLB / champion | 2473 | 0.247026 | 0.687039 | 0.0387 |
| MLB / poisson | 2473 | 0.249843 | 0.692897 | 0.0509 |
| MLB / negative_binomial | 2473 | 0.247726 | 0.688516 | 0.0388 |
| CFB / recency_ridge | 800 | 0.198033 | 0.577261 | 0.0720 |
| CFB / recency_boosted | 800 | 0.197012 | 0.576457 | 0.0533 |

### Probability calibration comparison

| Sport / recency ridge | Method | n | ML Brier | ML log loss |
|---|---|---:|---:|---:|
| NFL | raw | 284 | 0.227341 | 0.645321 |
| NFL | platt | 284 | 0.225237 | 0.638372 |
| NFL | isotonic | 284 | 0.232385 | 0.715513 |
| NFL | beta | 284 | 0.226109 | 0.640801 |
| MLB | raw | 2473 | 0.247857 | 0.688823 |
| MLB | platt | 2473 | 0.248100 | 0.689364 |
| MLB | isotonic | 2473 | 0.251713 | 0.800524 |
| MLB | beta | 2473 | 0.248258 | 0.689668 |
| CFB | raw | 800 | 0.198033 | 0.577261 |
| CFB | platt | 800 | 0.196921 | 0.574457 |
| CFB | isotonic | 800 | 0.199103 | 0.657455 |
| CFB | beta | 800 | 0.197125 | 0.574519 |

### Market diagnostics (raw Brier)

| Sport / retained baseline | ML | Spread | Total | Team total | Alt spread | Alt total |
|---|---:|---:|---:|---:|---:|---:|
| NFL / champion | 0.223282 | 0.210057 | 0.240240 | 0.230625 | 0.126047 | 0.230966 |
| MLB / champion | 0.247026 | 0.228882 | 0.248698 | 0.245543 | 0.013490 | 0.157104 |
| CFB / recency_ridge | 0.198033 | 0.208204 | 0.217040 | 0.210402 | 0.140172 | 0.242888 |

### Retained baseline ML calibration buckets

| Sport | Predicted bucket | n | Mean predicted | Observed hit rate | 95% hit-rate interval |
|---|---|---:|---:|---:|---|
| NFL | 50%–55% | 38 | 52.6% | 36.8% | 23.4%–52.7% |
| NFL | 55%–60% | 40 | 57.5% | 55.0% | 39.8%–69.3% |
| NFL | 60%–65% | 32 | 62.7% | 59.4% | 42.3%–74.5% |
| NFL | 65%–70% | 16 | 67.8% | 81.2% | 57.0%–93.4% |
| NFL | 70%–75% | 30 | 72.6% | 60.0% | 42.3%–75.4% |
| NFL | 75%–80% | 13 | 76.3% | 84.6% | 57.8%–95.7% |
| NFL | 80%–85% | 11 | 81.2% | 90.9% | 62.3%–98.4% |
| NFL | 85%–100% | 5 | 86.7% | 100.0% | 56.6%–100.0% |
| MLB | 50%–55% | 880 | 52.4% | 55.1% | 51.8%–58.4% |
| MLB | 55%–60% | 370 | 57.0% | 56.5% | 51.4%–61.4% |
| MLB | 60%–65% | 189 | 62.1% | 58.7% | 51.6%–65.5% |
| MLB | 65%–70% | 37 | 66.8% | 70.3% | 54.2%–82.5% |
| MLB | 70%–75% | 8 | 72.0% | 100.0% | 67.6%–100.0% |
| MLB | 75%–80% | 1 | 75.5% | 100.0% | 20.7%–100.0% |
| MLB | 80%–85% | 0 | — | — | — |
| MLB | 85%–100% | 0 | — | — | — |
| CFB | 50%–55% | 90 | 52.5% | 44.4% | 34.6%–54.7% |
| CFB | 55%–60% | 85 | 57.6% | 67.1% | 56.5%–76.1% |
| CFB | 60%–65% | 77 | 62.4% | 54.5% | 43.5%–65.2% |
| CFB | 65%–70% | 98 | 67.3% | 72.4% | 62.9%–80.3% |
| CFB | 70%–75% | 81 | 72.8% | 74.1% | 63.6%–82.4% |
| CFB | 75%–80% | 56 | 77.3% | 75.0% | 62.3%–84.5% |
| CFB | 80%–85% | 54 | 82.3% | 92.6% | 82.4%–97.1% |
| CFB | 85%–100% | 60 | 89.7% | 95.0% | 86.3%–98.3% |

NFL reference-market Brier: 0.210906; champion Brier 0.223282. The champion still underperforms that retrospective reference. MLB and CFB lack paired timestamped market benchmarks. Small buckets, especially NFL high-confidence buckets, cannot establish reliable accuracy.

## Model versions and market stages
- Retained NFL: `nfl-score-ridge-0.1.0-8b55af293d53`.
- Retained MLB: `mlb-score-ridge-0.1.0-792a7fe3fb48`.
- New CFB: `cfb-recency-ridge-0.2.0-02fb8f011cd5-2026-01` (trained and visible through local `get_model_status`; not live).
- Every moneyline, spread, alternate spread, total, alternate total, team total and alternate team total bucket remains SHADOW_ONLY, with zero frozen prospective validation results. Unsupported markets remain unavailable. No global approval flag can promote these fitted research artifacts.
- CFB supports FBS-v-FBS only; exact ID-joined team aliases, no FCS extrapolation, no CFB props. It has 800 retrospective 2025 evaluation games. Public archive receipt hashes and pinned source commit are saved. Ongoing CFBD refresh needs `JABBAZI_CFBD_API_KEY`; absent it, state becomes stale and inference stops rather than inventing updated inputs.

## Persistence and migrations
No destructive SQL migration is needed. The existing PostgreSQL/SQLite append-only `platform_events` store accepts versioned `source_pick`, `price_lifecycle`, `clv_record` and `frozen_forecast` evidence. Existing `model_prediction` gains feature/odds provenance and reliability payloads. Existing SQL immutability triggers and schema version 1 remain intact. `python -m jabazi.persistence.migrate` is idempotent. New source/lifecycle import contracts reject malformed or unauditable data; corrections append references and reasons rather than rewriting records.
The source schema does not scrape restricted capper services or grant their content redistribution rights. No source receives a learned performance weight without prospective outcomes.

## Tests and release status
See TEST_RESULTS.md for the final exact test count and CI result. Tests cover the exact Miami reproduction, signed alternate-pair regression, full ladders, pushes/complements, team-total identities, joint SGP dependence, stage demotion, calibration counts/monotonicity, recency/future labels, CFB inference/status/no-props, source immutability, CLV persistence, identity mismatches, duplicate events, drift, malformed-model isolation, explicit blend lanes and existing API contracts.
Local HTTP smoke verifies 200 liveness/readiness, 401 unauthenticated access, 200 authenticated database read and 503 missing odds provider. Production deployment has not occurred. GitHub CI verified PostgreSQL, Docker, the API/worker stack, backup/restore and database-outage behavior; exact commits and run links are in TEST_RESULTS.md. These checks do not constitute a production deployment.

## Exact rollout
1. Review the upgrade PR against `build/production-foundations` and require passing test/PostgreSQL/container/backup-restore CI. Preserve the separate member-experience work; do not force-push or merge the standalone V4.2 branch over the service.
2. Sign in to the existing Render workspace. Merge the reviewed upgrade into `build/production-foundations`. Both existing services have automatic deployment off; manually deploy the **same reviewed commit** to `jabbazi-research-api` and `jabbazi-research-worker`. No new paid service is required. The existing pre-deploy migration is unchanged.
3. Supply CFBD credentials via Render environment settings if ongoing CFB refresh is authorized; keep provider keys private. Keep model approval and unconfigured publishing disabled. Do not alter the bankroll or unit size.
4. Verify `/healthz`, `/readyz`, authenticated model status and existing MCP `get_model_status`. Require the CFB version above, seven team markets, SHADOW_ONLY and per-market buckets. Verify worker model refresh health. Run one explicitly authorized bounded research scan and read all retained pages; inspect frozen diagnostic evidence, freshness, anomaly state, zero stake and no Discord send.
5. Roll back both services to the previous reviewed commit if health/auth/API regressions appear. New event kinds are additive; retain their historical evidence. Do not delete or rewrite forecasts.

## What is still unavailable / incomplete
- No production rollout: Render sign-in required. No live CFB version, live anomaly quarantine or live signed-pair fix is claimed.
- No frozen prospective champion/challenger evaluation campaign; no model promoted to VALIDATING/LIMITED_LIVE/PRODUCTION_APPROVED.
- No validated personnel-aware NFL/MLB models, advanced CFB roster/talent/returning-production priors, or decision-time price backtest. Advanced-feature ingestion interfaces already existed and remain gated by real inputs.
- No approved NFL/MLB props, anytime-TD model, first-half/quarter model, player-linked SGP model, automatically mined capper feeds or provider-specific verified promo terms. Unknown probabilities/correlations remain unavailable.
- The new joint game helper supports team-market SGP research, but the scanner has no verified sportsbook combined-payout feed and does not manufacture SGP value.
- New source/price lifecycle/frozen forecast and Bob/promo/shrinkage helpers are implemented and tested; automatic source settlement, learned weights, nightly/weekly performance scheduling, and full live challenger fan-out are still pending.
- Probability calibrators are offline experiments. Serving them independently across markets would damage coherence. Joint-distribution calibration must be validated before live integration.
- Existing history uses delayed-score availability proxies. Historical QB/lineup/weather knowledge and original provider receipt snapshots cannot be reconstructed honestly from current feeds.
- Commercial display/redistribution rights for public-derived statistics and capper content need confirmation before a paid launch.

## Owner access / approvals needed
- Render sign-in to deploy the tested commit; no password or key in chat.
- CFBD API key and permission for the configured current-season refresh. The initial archived CFB training did not require a paid purchase.
- Timestamped historical odds/closing coverage entitlement (current The Odds API account or another permitted source); no purchase has been made.
- Legitimate timestamped NFL QB/injury/depth-chart/advanced-stat and MLB starter/lineup/bullpen/weather feeds, with commercial-use rights if displayed to members. No paid provider is selected or bought by this change.
- No request for sportsbook login, geolocation bypass, automated bet execution, or Discord publication.

## Next three highest-value improvements
1. Deploy these correctness fixes and start a frozen prospective, market-bucket evaluation ledger with paired current odds, closures and settled outcomes.
2. Add verified decision-time personnel/context feeds (NFL QB/injuries; MLB confirmed starters/lineups/bullpen) and measure feature ablations against the retained champions and market benchmark.
3. Improve the joint score distributions, including football tie/overtime treatment and distribution-level calibration, then reassess challenger promotion. Player props follow only after the team foundation clears its gates.

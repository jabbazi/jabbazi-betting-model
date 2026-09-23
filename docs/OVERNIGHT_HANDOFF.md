# JABBAZI NFL / MLB build handoff — September 23, 2026 UTC

## Scope and honest status

NFL and MLB full-game score-distribution **research models** are fitted and connected to the same `AutomaticScanner` used by the scheduled worker and authenticated `/v1/scans/run` API. This is not completion of the full NFL/MLB specification and is not production approval for paid picks.

Supported inference: two-way moneyline conditional on a decisive game, half-point spreads/run lines, totals, and offered alternate/team-total thresholds when compatible prices and participant identities are present. The current odds scan fetches standard moneyline/spread/total feeds. Capability to evaluate an alternate is not evidence that alternate/prop feeds are ingested.

Unavailable: trained player props, NFL anytime TD, MLB pitcher/batter props, F5/NRFI, quarters/halves, fitted SGP dependence, verified injury/lineup/weather inputs, and a proven profitable edge. Existing distribution/TD/parlay mathematics are frameworks, not fitted production models. CFB, NBA and tennis remain separate unfinished development.

## What changed

- Built separate frozen NFL and MLB two-output ridge score models. Standardization/coefficients fit through 2023, paired score residual distribution calibrated on 2024, diagnostic evaluation on 2025. No hyperparameter search on diagnostic results.
- Kept 2026 out of fitting and evaluation; recent completed results update current team feature state only. Two UTC date boundaries delay result availability. This is an approximation, not provider receipt-time historical evidence.
- Versioned compact artifacts ship inside the Python package. Inference does not require numpy/sklearn in the cloud.
- NFL schedule matches teams, kickoff and explicit neutral-site evidence. MLB schedule requires either explicit neutral-site data or a verified match to the home team's current venue.
- Worker refreshes recent results and schedule at most every six hours, under a database lease; it never retrains coefficients or approves models automatically.
- Latest refreshed artifacts persist as immutable `game_model` records in shared PostgreSQL, available to both API and worker. Refresh failure writes an unavailable marker, preventing silent fallback to an older healthy artifact.
- Stale (>36 hours), future-dated, missing-team, unsupported-market and in-play inference fails closed. Integer-line push outcomes are explicitly calculated by the model math, but rejected by the existing binary scanner until push-aware execution integration exists.
- Every scanner inference archives its model version, feature values, source/state checksums, schedule identity and observation timestamp in `model_prediction`. Scan records include model coverage counts.
- Full scans prioritize NFL, MLB and CFB before other leagues within the existing request budget. No new paid provider subscription or cloud service was purchased.
- Existing Discord commands stay unchanged: no member scanner access; cheat sheets retain three images per sport. Model results remain labeled research, and `BET_NOW` stays blocked.

## Evaluation (diagnostic, not proof of edge)

| Model | Training rows | Residual-calibration rows | Diagnostic rows | ML Brier | ML log loss |
|---|---:|---:|---:|---:|---:|
| NFL scores | 790 | 285 | 285 (284 decisive ML) | 0.223282 | 0.635409 |
| MLB scores | 7,219 | 2,469 | 2,473 | 0.247026 | 0.687039 |

NFL market comparison on the same 284 games: market Brier **0.210906**, better than the model. MLB has no paired historical odds. Neither dataset supplies decision-time historical price evidence for a credible ROI/CLV backtest. Do not market these models as validated/profitable.

NFL spread diagnostic Brier 0.210057 at fixed home -3.5; total Brier 0.240240 at fixed 44.5. MLB spread Brier 0.228882 at fixed home -1.5; total Brier 0.248698 at fixed 8.5. These fixed thresholds are experiments, not historical offered prices or betting returns. Full reliability buckets are in `docs/experiments/score-distributions/`.

The policy haircut of 0.08 is explicitly a conservative research setting, not a measured confidence interval. Stronger pitcher/QB/efficiency features remain necessary. Earlier MLB Elo and NFL scoring-logistic experiments are preserved.

## Validation and deployment evidence

Local suite before deployment: 160 tests passed, including real scanner-to-cloud-artifact-store integration, shadow-only enforcement, stale/unsupported inputs, venue identity, sign/push math, inference audit persistence, refresh failures/throttling, and diagnostic-label leakage tests. Cloud deployment and live inference verification will be appended after they actually complete.

## What the owner needs to do

No new login was needed for the work above. Keep the private API credential private. The owner desk uses the existing `JABBAZI_MODEL_TOKEN`; enter it directly in the app, never in chat or Discord.

Before commercial launch, resolve these concrete data gaps:

1. Confirm historical-odds access with the configured odds provider, including decision-time snapshots and prop history. Existing current-odds credentials do not prove that entitlement.
2. Obtain/confirm commercial rights for the data and derived outputs used in paid sheets/picks. Public access is not blanket commercial permission; no license was assumed or purchased in this build.
3. Select licensed NFL usage/injury/depth-chart and MLB starting-pitcher/lineup/player-log coverage. Essential for the requested player models. Provider selection and any purchase require a concrete quote/approval.
4. Complete prospective prediction logging and outcome/CLV evaluation before model promotion. No promise that more data guarantees a profitable model.

Chat phrase “scan everything” is not a newly installed ChatGPT action. The cloud API's authenticated full-scan path uses the models; an external chat/app must call that API with owner authorization. Discord members cannot invoke it.

A one-time morning handoff is scheduled for approximately 8 a.m. America/Chicago September 23, 2026. It reports verified state; it is not a promise of continuously running overnight engineering.

## Verified live cloud result

Application commit `23557f6a4602388a93aba77ad2d17266f6da3b4b` deployed successfully to both existing Render services:

- Worker: live September 23 2026 04:03:51 UTC, deployment `dep-dapkv067bikc73fs7450`.
- API: deployment succeeded and live; HTTP `/healthz` and `/readyz` returned 200, database ready. Unauthenticated `/v1/model-status` and `/v1/owner/review` returned 401.
- First worker heartbeat (started 04:03:52 UTC; visible log 04:04:25 UTC): NFL `SHADOW_READY`, 32 teams and 17 scheduled events; MLB `SHADOW_READY`, 30 teams and 76 scheduled events.
- Live scan: 3 feeds, 2,832 quotes, **190 model-backed research actions**, no scan errors, both model versions present, Discord process RUNNING, betting_enabled=false.
- Model versions: `nfl-score-ridge-0.1.0-8b55af293d53` and `mlb-score-ridge-0.1.0-792a7fe3fb48`.

An existing CI setup defect surfaced: unit-test job installed only dev dependencies, so Discord image imports failed before collection. Fixed in `7fb4750cb5c66829b8f40c82c047e8e0c8194ca8` to install dev, Discord, and research extras. That change affects CI only; no unnecessary production restart is required. Container build, API/worker stack checks, database backup/restore and database-outage checks already passed on the application commit. Final CI result follows below when verified.

Final CI verification: workflow run `35816871496` on `7fb4750cb5c66829b8f40c82c047e8e0c8194ca8` passed both `tests` and `container` jobs. This includes the full test suite, authenticated API smoke check, Docker build, PostgreSQL-backed service readiness, backup/restore and outage handling. Application runtime remains the verified `23557f6` deployment; later commits only change CI/documentation.

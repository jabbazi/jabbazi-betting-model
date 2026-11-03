# Data-trust validation release — September 28, 2026 UTC

## Findings and implemented changes

- Production at inspection: 067f641 (PR #8). Render API and worker use this repository and production branch; auto-deploy is disabled.
- Live SportsDataIO NFL and MLB projections still return HTTP 401. Authentication is not proof of accurate production data. New collectors quarantine SportsDataIO projections unless `JABBAZI_SPORTSDATAIO_DATA_MODE=PRODUCTION_VERIFIED` is explicitly set after validating real feed access and the account agreement. Do not set it for a free trial. The status endpoint separately reports connectivity and data authenticity.
- Existing SportsDataIO feature snapshots without `provider_data_verified: true` are rejected at inference. Audit records remain immutable; no deletion or retrospective rewriting.
- Fixed explicit `research_only=True` being lost when all integrity flags were true; approval also independently checks the stored restriction.
- Player inference now checks event start equality, timezone-aware timestamps, pregame availability, future timestamps, and a one-hour snapshot age limit. These checks protect direct inference, not only scanner presentation.
- MLB player history is sorted, deduplicated by game ID, and filtered by a conservative two-day availability proxy. NFL player rows are joined to completed schedule games and admitted only after a two-day availability proxy. These proxies are not historical receipt-time proof; suspended/resumed MLB historical receipt verification remains a limitation.
- NFL depth-chart URLs use the current football season rather than a fixed 2026 file. NFL feature checksums now include the full projection payload rather than only PlayerID.
- NBA has a tested aligned player-sample distribution contract for points, rebounds, assists, threes and combinations. Joint probabilities preserve sample dependence. Cross-player/event combinations and unsupported DNP/push settlement fail closed. This is not a trained NBA model, minutes forecaster, live provider, or betting-approved service. API status explicitly reports NBA UNAVAILABLE.

## Reproducible evaluation

Run `python tools/verify_frozen_evaluation.py`. It independently re-scores committed frozen retrospective predictions and checks n/Brier/log loss against stored reports. It does not retrain models or create an untouched holdout. Run `python tools/diagnose_miami.py` for the artifact-based historical arithmetic reproduction.

| Sport | Model | ML n | Brier | Log loss |
|---|---|---:|---:|---:|
| NFL | champion | 284 | .223282 | .635409 |
| NFL | recency ridge | 284 | .227341 | .645321 |
| NFL | boosted | 284 | .227415 | .647120 |
| MLB | champion | 2473 | .247026 | .687039 |
| MLB | recency ridge | 2473 | .247857 | .688823 |
| MLB | boosted | 2473 | .249175 | .691515 |
| MLB | Poisson | 2473 | .249843 | .692897 |
| MLB | negative binomial | 2473 | .247726 | .688516 |
| CFB | recency ridge | 800 | .198033 | .577261 |
| CFB | boosted | 800 | .197012 | .576457 |

No NFL/MLB challenger beats the champion on these Brier scores. Calibration tables and per-market metrics remain in `docs/experiments/reliability-upgrade/{nfl,mlb,cfb}/report.json`; the verification command emits full re-scored tables. No new probability calibration or promotion is claimed. Historical prices have no verified decision timestamps; execution ROI/CLV remain unavailable.

Miami +10.5 reproduces as 232/285 = 81.404%, with a near-even predicted score. Six of eight equally weighted prior games were from 2025; no QB/injury features were used. No spread-sign bug is established. This is a committed-artifact reproduction, not retrieval of the full original production feature record. Its structural model weakness remains; quarantine is required.

## Remaining launch gates

1. Verified production NFL/MLB projections and required personnel feeds, with rights for the intended commercial use. NBA needs historical player/minutes/team data and current injury/rotation inputs before training or live coverage.
2. Audit all persisted cloud feature records for provenance. The current read-only scanner tools do not export all historical player snapshots. Old unverified SportsDataIO records cannot drive inference after this change, but this is containment, not proof of a completed database contamination audit.
3. Better personnel-aware team features, minutes/role player models, timestamped market benchmarks and frozen prospective evaluation. Team models remain SHADOW_ONLY; player models remain research-restricted. No profitability or production approval is established.

No database migration: additive JSON snapshot/status fields. No secrets, purchases, automatic wagers, Discord posts or role changes. Deployment verification is recorded in the PR after CI and live checks.

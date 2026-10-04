# Opponent-adjusted score experiment results

**Research completed; no live model replacement or promotion.**

Fixed protocol: [PROTOCOL.md](PROTOCOL.md). 408 automated tests passed, including seven new chronological/orientation/joint-distribution regressions. Existing probability and scanner tests remain green.

## Moneyline diagnostics

Lower Brier and log loss are better. The CFB comparison uses its frozen per-game rolling baseline on the same covered games.

| Sport | Decisive games | Baseline Brier | New raw Brier | Joint-calibrated Brier | Baseline log loss | Joint-calibrated log loss |
|---|---:|---:|---:|---:|---:|---:|
| NFL | 284 | 0.223282 | 0.250909 | 0.247857 | 0.635409 | 0.688958 |
| MLB | 2473 | 0.247026 | 0.246609 | 0.246197 | 0.687039 | 0.685443 |
| CFB | 786 | 0.196621 | 0.225347 | 0.224420 | 0.574099 | 0.639950 |

NFL and CFB moneylines deteriorated. MLB moneyline Brier improved by about 0.00083 per game, but its equal-week-weight comparison is worse by 0.00072 with a 95% bootstrap interval of approximately [-0.00444, +0.00602]. That is not convincing improvement. Some market point estimates improve, but no tested model demonstrates enough evidence for promotion. No hyperparameters were retuned after seeing these results.

## Evidence and scope

Each sport folder contains the final-fold research artifact, frozen predictions and full report with Brier/log loss, calibration intercept/slope, reliability buckets, row-based descriptive intervals and week-block paired comparisons. CFB covers 786 of 800 candidate games; 14 were unavailable under the training-team/baseline coverage checks. Report exclusions rather than filling unknown identities. NFL has 285 games but 284 decisive moneyline labels; the tie is excluded only from the conditional moneyline metric.

Whole ISO-week blocks are equally weighted in the paired uncertainty diagnostic; the point estimate therefore differs from per-game Brier. Confidence intervals are descriptive and do not resolve multiple comparisons, temporal regime change or repeated examination of 2025. Calibration tables do not establish betting readiness.

## Reproduction

Install `.[research]`, extract the separately retained source archive `JABBAZI_opponent_experiment_inputs_20260928.zip`, then run:

```bash
python -m jabazi.research.opponent_scores nfl /path/to/nfl.json /new/output/nfl
python -m jabazi.research.opponent_scores mlb /path/to/mlb.json /new/output/mlb
python -m jabazi.research.opponent_scores cfb /path/to/cfb.json /new/output/cfb
```

Reports retain hashes of the exact source, training code, baseline artifact and CFB baseline predictions. Current normalized provider inputs were retained separately, rather than publishing another raw source copy in this public repository.

## Tomorrow readiness — September 28, 2026 Central

Live checks still return SportsDataIO HTTP 401 for NFL PlayerGameProjectionStatsByWeek and MLB PlayerGameProjectionStatsByDate, with production data UNVERIFIED. NFL/MLB/CFB teams remain SHADOW_ONLY, registered player models VALIDATING and NBA UNAVAILABLE. No probability recalibration was installed in the live scanner. Existing research scanning remains available; model output cannot establish a cash recommendation.

To progress: obtain production feed permissions and commercial-use terms; fit personnel/role-aware features using trustworthy history; collect frozen prospective predictions and exact closing quotes. NBA still requires training and verified inputs. Historical receipt-time and production database provenance audits remain outstanding. No Discord publishing, purchases or wagers occurred.

# NHL goals model — 2026-09-28

Version: `nhl-poisson-form-0.1.0-ece6dbc3008b`. All seven market buckets are **SHADOW_ONLY**. NHL player props are **UNAVAILABLE**.

## Data and scope

Captured 128 official NHL club-season responses covering 5,248 unique completed regular-season games (1,312 per season, 2022–23 through 2025–26). Both club views must agree. Raw captures are preserved privately as `JABBAZI_NHL_inputs_20260928.zip`; public checksums and source URLs are in [source_receipts.json](source_receipts.json).

Fit sample: 2591 games. Calibration: 1310 games. Untouched evaluation: 1312 games. Selection alpha: 0.01. Shared goal-rate calibration factor: 0.995516. See the pre-evaluation [protocol](PROTOCOL.md).

Regular-season moneyline, puck line, alternate puck lines, game totals, alternate totals, team totals and alternate team totals derive from one joint goal distribution. Independent Poisson regulation goals are followed by a fitted pooled OT/shootout winner model. A tied regulation score receives exactly one deciding goal. First-period, regulation-only, playoffs and player markets are unsupported. Whole-number thresholds with push mass are withheld from the scanner’s binary EV calculations.

Book-specific rules remain unverified. The declared full-game research settlement includes overtime and one shootout deciding goal. This is not permission to apply that convention to every book or team-total contract.

## Untouched 2025–26 evaluation

Each row below contains 1,312 independent games. Lower Brier/log loss is better. The baseline is league-average scoring, **not sportsbook consensus**. Spreads/totals use fixed diagnostic thresholds, not reconstructed bets.

| Market | Baseline Brier | Model Brier | Baseline log loss | Model log loss | Model ECE | Paired Brier difference 95% interval |
|---|---:|---:|---:|---:|---:|---|
| Home moneyline | 0.249685 | 0.246858 | 0.692518 | 0.686787 | 0.020049 | [-0.005563, -0.000038] |
| Home -1.5 | 0.210642 | 0.206353 | 0.612289 | 0.601960 | 0.017664 | [-0.006515, -0.002130] |
| Over 6.5 | 0.251068 | 0.249790 | 0.695347 | 0.692803 | 0.038835 | [-0.003431, 0.000724] |
| Home over 3.5 | 0.241884 | 0.238983 | 0.676869 | 0.670824 | 0.019404 | [-0.005435, -0.000343] |

Moneyline, puck-line and team-total Brier differences favor the form model in this sample. Totals remain inconclusive. Intervals use paired game bootstraps and are descriptive, without multiple-comparison adjustment or a guarantee of season-to-season robustness. The calibration factor slightly worsened several held-out metrics compared with the raw form model; it was not retuned on that test season.

All raw/calibrated/baseline scores, reliability bins, Wilson hit-rate intervals, calibration slopes/intercepts and game snapshots are in [report.json](report.json) and `test_predictions.json.gz`. Calibration slope for a nearly constant baseline is weakly identified and should not be treated as a skill measure. No valid market comparison, CLV, ROI or prospective performance exists yet.

## Reliability and remaining limits

- Model version, exact feature vectors/history, source checksums, quote IDs and code commit are frozen with scanner predictions.
- Recency weighting: 90-day half-life, 365-day horizon, ten league-average pseudo-games. Offseason history decays; Arizona is not silently treated as Utah. Utah franchise name changes use an explicit alias.
- Historical result availability is a conservative start-plus-48-hours proxy, not an archived publication timestamp. Corrections could have arrived later. This limits retrospective claims.
- Missing confirmed goalie, lineup, injury, special-teams and shot-quality inputs. No empty-net tactical model. Regulation score dependence is not fitted beyond OT tie resolution.
- The current artifact is scoped to 2026–27. A new season requires a reviewed artifact refresh, not silent relabeling.
- Zero frozen prospective games at release. All probabilities remain research-only. A new reviewed model release is required before any promotion.

## Scanner integration and reproduction

`registry.load_models` loads `nhl_goals.json`, with latest persisted state taking priority and failed refreshes blocking fallback. The bounded six-hour worker refresh reads current official club schedules, merges results, archives result corrections and refreshes future events. `scan_everything` includes NHL within existing credit limits; alternate/team-total feeds rotate within the same budget. `get_model_status` exposes the NHL version and seven research-only buckets. `get_scan_results` retains existing pagination and schemas.

Team totals now route to team models, never player feature collectors, player forecasts or player exposure tags. NHL feed failures cannot fabricate probabilities or stop unrelated sports. Database migrations: none; existing append-only game-model, prediction, result and scan records are reused.

```bash
python -m pip install '.[research,dev]'
python tools/capture_nhl_history.py --output /private/nhl-inputs --opening-date 2026-09-29
python -m jabazi.research.nhl_experiment --inputs /private/nhl-inputs --output docs/experiments/nhl-goals --artifact src/jabazi/models/artifacts/nhl_goals.json
python -m pytest -q
ruff check src tools tests --select F
```

To reproduce this exact capture, extract the preserved ZIP instead of downloading potentially corrected current responses. The regression suite tests fixture prices, not live sportsbook validity.

## Deployment procedure

CI must pass on the PR targeting `build/production-foundations`. Merge the verified head, then trigger the existing Render API (`srv-dapfgeff3r2c73citeog`) and worker (`srv-dapfub1srm7s73fbo7cg`); auto-deploy is disabled. Verify both deployed commit IDs, `/healthz`, `/readyz` and authenticated `get_model_status`. No secrets, environment changes, new service or paid subscription are required for this NHL research baseline. Live deployment evidence is recorded in the PR after verification.

Highest-value follow-ups: confirmed goalie/lineup history with publication timestamps; timestamped no-vig prices and frozen prospective evaluation; overdispersed/dependent goal challengers including shot quality, special teams and empty-net state.

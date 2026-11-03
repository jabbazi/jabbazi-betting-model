# NFL scoring-form challenger — September 23, 2026

**Decision: research only; rejected for paid-pick deployment.**

This is a real fitted logistic game-winner experiment, not a props, spread, total,
SGP or touchdown model. It adds an executable feature pipeline and separate
logistic calibration to the existing research platform. It is not registered in
the production scanner.

The preserved 1,455-game history supplied 787 eligible decisive training games
through 2023, 285 calibration games from 2024 and 284 diagnostic games from 2025.
The 31 supplied 2026 rows were excluded. Four prior completed games per team are
required; eight-game rolling scoring/conceding form, capped rest differential
and neutral-site-adjusted home field are the six features. Only training data
fits the scaler and model. Calibration uses 2024 only. There is no parameter search.

| 2025 diagnostic, same 284 games | Brier | Log loss |
|---|---:|---:|
| Training home-rate reference | 0.249163 | 0.691478 |
| Uncalibrated scoring-form model | 0.225263 | 0.639965 |
| Separately calibrated model | 0.225521 | 0.640925 |
| No-vig market diagnostic | 0.210906 | 0.606989 |

Lower is better. Calibration did not improve these diagnostic scores. Both model
variants trail the market. Do not select the uncalibrated variant after looking
at this test and then call that choice independently validated. No statistical
significance or profit claim is made. Raw probability buckets and metrics are in
report.json; the coefficient/scaler/calibration artifact is in artifact.json.

2025 was previously inspected for Elo, so these results are explicitly diagnostic,
not an untouched final holdout. Historical quote timestamps are absent. There is
no point-in-time ROI/CLV backtest. The two-UTC-day label availability delay remains
a conservative proxy, not verified provider publication times. Ties are excluded
from binary scoring. QB, injuries, EPA, weather and player usage are not included.

Next data work: construct provider-timestamped weekly efficiency/QB/availability
snapshots and join them to historical decision-time odds. Keep result history
and actual feature availability distinct; reject incomplete or future inputs.
Compare additions to this frozen specification without iteratively tuning on 2025.

## Reproduce

Install the optional `research` dependencies, then run:

```
python -m jabazi.research.nfl_challenger PATH_TO_NFL_HISTORY_JSON OUTPUT_DIRECTORY
```

The input source SHA-256 is stored in both JSON files. The preserved source is
`jabbazi-launch-kit/scanner/data/nfl_history.json` in the working environment.
The script also emits row-level diagnostic predictions for audit; source data
and row-level outcomes are not republished in this commit.

Verification: 143 local tests passed, including five new feature tests covering
current/future result exclusion, same-day results, minimum coverage, ties,
duplicate game IDs and the result-availability delay. The real fit and diagnostic
run completed successfully. Existing upstream dependency warnings remain.

# Opponent-adjusted joint score experiment, September 28, 2026 UTC

Fixed before running these diagnostics: one recency-weighted ridge score equation with offense-team and opposing-defense indicators, venue effect and rest difference. Ridge alpha 20. Result half-lives NFL 365 days, MLB 180, CFB 240. Team effects shrink toward league scoring through regularization. No personnel priors or injury adjustment is claimed.

Monthly expanding origins during season 2025. At each origin, separate earlier fitting games, an out-of-fit residual window, a later joint-moment calibration window, and subsequent evaluation games. Window sizes are 120 NFL, 300 MLB, 160 CFB games, with whole date boundaries and two-day label-availability gaps. Unknown team identities are unavailable, not invented averages. All 2026 outcomes are excluded before feature construction.

Variants: raw paired residual distribution; one affine mean/covariance recalibration of the paired residuals using the disjoint calibration window (10% target covariance shrinkage toward diagonal). Each variant derives every market from one nonnegative integer paired-score distribution. Calibrating moments does not establish probability calibration or correct tail behavior.

Compare against existing NFL/MLB champions on the same games. CFB uses frozen per-game rolling ridge baseline predictions because its final bundled artifact includes later 2025 training games. Do not evaluate that artifact retrospectively on earlier folds.

Report Brier, log loss, calibration intercept/slope, reliability buckets and uncertainty per market. Paired model-minus-baseline Brier uncertainty uses ISO-week blocks. Fixed thresholds diagnose distributions; they are not historical offered bets. No ROI or CLV claims. Previously viewed 2025 data is diagnostic only, never an untouched final holdout. No architecture promotion or live scanner replacement is authorized by this experiment's results alone.

Historical receipt times remain a two-day proxy. Missing QB/starter/lineup/injury/weather inputs and sport-specific overtime/extra-inning settlement modeling remain launch blockers. No CFB player props.

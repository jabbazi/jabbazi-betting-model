# NFL anytime touchdown experiment, declared before evaluation

Use captured nflverse weekly player statistics, seasons 2021–2025 only, from the
existing checksum-pinned manifest. Exclude 2026 before constructing features.
Predict the chance of at least one rushing or receiving touchdown, conditional on
appearing in the weekly statistics archive. This is not an all-roster population:
zero-opportunity participants, DNPs and return-only touchdowns require separate
participation/settlement evidence before deployment.

Baseline: existing frozen ATD logistic artifact, with its original step calibration.
Challenger: fixed regularized logistic regression (C=0.2), with recency half-life
365 days. Features: separate prior rushing/receiving opportunities and touchdowns,
lagged team scoring opportunity and opponent touchdowns allowed, position,
home field, season transition, days since last appearance, prior sample count.
No fabricated red-zone, goal-line, injury or projected-snap features.

Fit through 2023-12-31; fit monotone logistic calibration during calendar 2024;
evaluate calendar 2025. Fit/scaler/calibrator never see evaluation outcomes.
Report raw and calibrated challenger without choosing a variant from test results.
Game rows are grouped; outcomes must be available before fold boundary. Reconstruct
availability using scheduled start + 2 days, explicitly not archived receipt times.

Compare matched player/game predictions, calibration tables, position splits and
paired game-cluster bootstrap Brier differences (500 deterministic resamples).
A chronological holdout already overlapping an earlier examined period is a
retrospective diagnostic, not an untouched or prospective test. No sportsbook
prices means no market-relative edge, CLV or ROI claim. No automatic registration
or promotion, even if this diagnostic improves.

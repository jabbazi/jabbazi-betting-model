# NHL goals baseline: frozen evaluation protocol

Defined before inspecting evaluation metrics, 2026-09-28 UTC.

- Official NHL club schedules only; completed regular-season games. Exclude preseason and playoffs. Deduplicate the two club views and reject disagreements in identity, venue, time, or score.
- Reconstruct regulation scores by removing the single deciding goal from the overtime/shootout winner; reject malformed outcomes.
- Training: 2022–23. Hyperparameter selection: 2023–24; refit on both seasons. Goal-rate calibration: 2024–25. Untouched evaluation: 2025–26.
- Sequential features use results with an explicit conservative start-plus-48-hours availability proxy. This is a retrospective experiment; the original publication-time snapshots are unavailable. No historical odds or goalie/injury inputs are inferred.
- Challenger: regularized Poisson regression of regulation goals on recency-weighted own goals-for, opponent goals-against, venue, rest and opponent rest. Ten league-average pseudo-games, 90-day half-life, maximum 365-day history. Independent regulation goal counts. A separately fitted pooled overtime/shootout home-win rate resolves tied regulation scores.
- Candidate regularization strengths: 0.01, 0.1, 1.0. Select by goal Poisson negative log likelihood on 2023–24, not ROI. Calibrate only the shared multiplicative goal-rate factor using 2024–25; all market probabilities still derive from one joint distribution.
- Baseline: fitted league-average home and away goal rates, with the same overtime treatment and rate-calibration procedure.
- Evaluate moneyline, home -1.5, over 6.5, home over 3.5. These fixed thresholds are mathematical diagnostics, not reconstructed historical wagers. Report Brier, log loss, calibration tables and sample counts. No ROI, CLV or market-relative advantage without timestamped prices.
- Deployment: SHADOW_ONLY regardless of these results. Missing prospective evidence, book-specific settlement confirmation, confirmed goalie/lineup/injury feeds and point-in-time data prevent cash approval.

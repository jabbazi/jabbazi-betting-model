# NFL/MLB moneyline development experiment, September 23, 2026

This protocol is recorded before running the new challenger on the saved real
history. It is a finite development experiment, not a registered independent
test. Previous JABBAZI experiments have already examined the 2025 season.

## Fixed design

- Admit 2021–2025 completed games only. Exclude every 2026 game from fitting,
  selection, calibration, diagnostic scoring and feature/rating updates.
- Generate features chronologically using the existing two-UTC-date result
  availability proxy. Current, same-day and future outcomes cannot affect a
  game's features. This proxy still needs true provider publication timestamps.
- Compare two feature families: the existing six score/rest/home-field features,
  and those six plus a lagged opponent-strength Elo logit. Elo parameters are
  fixed in the protocol; no retrospective price is used as a feature.
- Fit on 2021–22; compare C = 0.1, 1, 10 for both families on 2023 log loss.
  Keep all six trials, including losers, in the report.
- Refit the selected family/C through 2023. Fit logistic calibration on 2024
  predictions only, with C = 1. Report both calibrated and uncalibrated 2025
  predictions, but do not choose between them using 2025 outcomes.
- Report Brier, log loss, AUC, reliability buckets, descriptive calibration gap,
  sample sizes and paired comparisons against the frozen score model and no-vig
  market where available. Use the same games for both sides of a comparison.
- Report descriptive 95% intervals from 1,000 paired UTC-week bootstrap draws,
  seed 20260923. They do not remove all team/time dependence or selection bias.
- Exclude ties from binary moneyline scoring and count them. These probabilities
  are conditional on a decisive game; there is no new settlement/void model.

## Controls and deliverables

Write coefficients, all diagnostic predictions and a report with source,
admitted-data, comparator, protocol and code checksums plus package versions.
Refuse a comparator whose sport/source differs. Never overwrite the bundled
production artifacts. No registry, live API, worker, stake or approval flag changes.

The input files contain no decision-time-verified historical odds. NFL prices
can support a retrospective paired diagnostic only. MLB has no paired prices.
ROI, execution slippage and CLV must remain unavailable, not be inferred from
classification scores. Raw provider data is not committed or redistributed.

Even an improved diagnostic result cannot remove SHADOW_ONLY. Next gates are
licensed point-in-time sport-specific features, valid paired odds, untouched
forward evaluation, calibration review, execution/CLV/ROI evidence and explicit
reviewed promotion. A 100-row split floor is an engineering guard, not a power
calculation or sufficient evidence of quality.

## Method references

- https://scikit-learn.org/stable/modules/cross_validation.html
- https://scikit-learn.org/stable/modules/calibration.html

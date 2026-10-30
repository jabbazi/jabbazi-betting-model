# Advanced model validation enforcement

This document records the first production-enforceable subset of the JABBAZI advanced
validation specification.

## Model stages

- SHADOW_ONLY
- VALIDATING
- LIMITED_LIVE
- PRODUCTION_APPROVED
- QUARANTINED

Integrity failures may quarantine immediately. Winning/losing streaks alone do not
promote or quarantine models.

## Model-market disagreement

Default starting thresholds are:

- NORMAL: <5 probability points
- LARGE_DISAGREEMENT: 5-10 probability points inclusive
- EXTREME_DISAGREEMENT: >10 probability points

Extreme disagreement is a safety-review trigger, not a larger-stake signal.

## Production demotion defaults

A PRODUCTION_APPROVED model moves to LIMITED_LIVE when supported evidence indicates
material deterioration, including:

- rolling ECE >5 percentage points after at least 100 effective observations;
- relative Brier deterioration >5% after at least 100 effective observations;
- mean probability-based CLV <0 after at least 150 effective qualified entries and
  at least 90% confidence that the true mean is negative;
- required-feature coverage <97%;
- stale/invalid critical prediction rate >1%;
- material feature/prediction drift.

Confirmed leakage, identity failures, market mapping failures, or model/version
mismatches quarantine immediately.

## High-variance markets

Initial defaults for NFL anytime TD, MLB HR, NHL goal scorer, first scorer, longshot
props, and parlays/SGPs:

- LIMITED_LIVE: effective prospective N >=250 and >=8 weeks where calendar permits;
- PRODUCTION_APPROVED: effective prospective N >=600 and >=12 weeks;
- LIMITED_LIVE stake cap: 0.25u;
- initial PRODUCTION_APPROVED stake cap: 0.50u.

Correlated alternates or same-game observations must not be counted as independent.

## Configuration

Machine-readable defaults live in `config/validation_profiles.json`. These are
starting policy values, not evidence that any current model has passed them.

The next implementation phases are effective-sample estimation, confidence intervals,
evidence cards, promotion reports, market-specific profiles, and automatic rollback /
canary controls.

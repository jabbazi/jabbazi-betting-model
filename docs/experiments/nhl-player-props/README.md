# NHL player-prop research pipeline

Status: **research-only / not approved for betting**

This experiment extends the deployed NHL team-model plumbing with an independently
validated player-prop lane. Odds availability is not treated as model availability.

## Initial modeled tranche

The first historical/live feature path is limited to:

- player shots on goal
- player points
- player assists
- player goals
- goalie saves

The scanner may ingest additional NHL markets (power-play points and blocked shots),
but those markets intentionally have no live feature snapshot until their per-game
historical source is validated.

## Data path

1. tools/capture_nhl_history.py captures official NHL club schedules/results.
2. tools/capture_nhl_player_history.py captures official per-game skater/goalie
   Stats REST summaries for 2022-23 through 2025-26.
3. jabazi.research.nhl_player_experiment reconstructs each historical prediction
   using only player results available before the decision timestamp. Team schedule
   results use the existing conservative 48-hour availability lag.
4. tools/train_nhl_player_props.py performs chronological train/calibration/test
   fitting through the existing generic player-distribution framework.
5. Trained artifacts are written to a private output directory. They are not copied
   into models/player_props or deployed automatically.

## Probability family

All first-tranche NHL targets are non-negative integer counts. The existing player
framework fits a regularized conditional mean and estimates an NB2 dispersion term,
then converts each sportsbook threshold into an explicit tail probability. A projected
mean is never used as if it were a hit probability.

Whole-number thresholds remain unavailable in the scalar EV lane because push
settlement is not represented by the binary win/loss pricing contract.

## Fail-closed live integrity

Official NHL history and current rosters can establish player identity and recent
usage. They do not establish:

- same-day injury/scratch status,
- line assignment,
- power-play unit assignment,
- confirmed starting goalie,
- sportsbook-specific settlement differences.

The live collector therefore archives NHL features as research-only whenever these
facts are not independently verified. A goalie-saves snapshot always fails the role
gate until a verified starter source is added.

## Promotion gates

Historical fitting can produce only SHADOW_ONLY or VALIDATING research artifacts.
Production approval still uses the generic frozen prospective gates, including:

- at least 500 held-out distribution observations,
- at least 500 prospective priced observations from 500 independent events,
- model Brier at least 0.002 better than market baseline,
- prospective ECE <= 0.04,
- at least 150 CLV observations from 150 independent events with non-negative mean CLV,
- zero data-health failures,
- zero result-identity failures.

Historical prop-price evidence is currently absent from the first build. That means
the first useful milestone is a calibrated outcome distribution plus prospective
price collection, not a betting card.

## Next research steps

- verify the NHL Stats REST per-game schema against a fresh private capture;
- run the four-season capture and train all five first-tranche artifacts;
- inspect held-out distribution error and dispersion by market/position;
- add verified same-day lineup/injury and starting-goalie evidence;
- start immutable prospective forecasts against current no-vig market probabilities;
- only then evaluate LIMITED_LIVE or PRODUCTION_APPROVED promotion.

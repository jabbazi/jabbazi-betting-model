# JABBAZI V5 research architecture

Status: **research-only overlay; no new cash authority**

V5 deepens the existing V4.2 reliability system rather than replacing its safety gates.

## 1. Scenario engine

Team models already preserve paired score residual scenarios. V5 exposes those scenarios
as the canonical source for correlated same-game team-market probabilities.

- same-event legs: direct joint frequency from shared game scenarios;
- distinct-event legs: marginal product is permitted only with an explicit independence
  label and propagated uncertainty bounds;
- no multiplication of correlated same-game marginals;
- 2-4 legs only in the initial research contract;
- every ticket carries event/market/subject concentration keys.

Player-team SGPs remain unavailable until player outcomes are generated inside the same
aligned game scenarios.

## 2. Opportunity-first player architecture

Each player market now declares its opportunity unit:

- NFL: attempts, targets, carries, high-value opportunities;
- NBA: minutes;
- NHL: TOI or shots faced;
- MLB: plate appearances or batters faced.

The first-stage opportunity estimate has its own mean, uncertainty interval, model
version and input-verification state. Outcome distributions may consume a bounded
opportunity adjustment only after sport-specific opportunity artifacts are trained and
prospectively validated.

## 3. Market intelligence and CLV

V5 adds immutable exact-market snapshots containing:

- event/date/market/selection/participant/threshold;
- all observed book prices;
- best price;
- consensus no-vig probability;
- source timestamp and quote IDs.

Closing-line value is computed only between exact matching market identities. Both
probability-space CLV and price-space CLV are retained. Results and CLV remain separate
metrics: a winning bet can have negative CLV and a losing bet can have positive CLV.

## 4. Segmented calibration

Calibration is evaluated by sport, market bucket, favorite/underdog state and edge band.
This prevents good aggregate calibration from hiding a systematically overconfident
sub-market.

## 5. Kill switches

V5 automatically removes cash influence for identity or data-health failures and moves
research lanes to WATCH for:

- feature drift;
- repeated provider failures;
- calibration deterioration with adequate sample;
- market-relative Brier deterioration with adequate sample.

These switches can downgrade evidence state; they cannot promote a model.

## 6. Next granular feature work

The contracts are intentionally sport-agnostic. Sport-specific feature releases should
be added behind point-in-time provenance:

- NFL: route participation, target/air-yard share, red-zone/high-value opportunities,
  personnel grouping, pressure/coverage and neutral-script tendencies;
- NHL: shot attempts, unblocked attempts, high-danger chances, xG, PP deployment,
  line combinations and opponent shot suppression;
- NBA: possessions, touches, usage by lineup, potential assists, rebound chances,
  shot-location profile, pace and minutes/rotation state;
- MLB: pitch arsenal/velocity/spin, whiff/CSW, batter pitch-type splits, contact quality,
  park/weather, umpire and bullpen availability.

No feature is eligible for production inference unless its timestamp proves it existed
before the decision point.

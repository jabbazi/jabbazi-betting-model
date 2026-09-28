# JABBAZI model completion matrix — 2026-09-28

"Complete" means the engineering/data path exists and the model reports its evidence
state honestly. It does **not** mean every market is approved for wagering.

| Sport / lane | Engineering state | Current evidence state | Blocking evidence |
|---|---|---|---|
| NFL team ML/spread/total/derivatives | implemented | SHADOW_ONLY / prospective validation | personnel context, prospective market-relative evidence |
| NFL player volume/yardage | implemented | VALIDATING | verified production role/injury feed; prospective priced evidence |
| NFL anytime TD | implemented + challenger audited | VALIDATING | challenger did not establish improvement; verified role/injury feed |
| MLB team ML/spread/total/derivatives | implemented | SHADOW_ONLY / prospective validation | convincing market-relative improvement + prospective evidence |
| MLB batter/pitcher props | implemented | VALIDATING | verified production projection/lineup feed + prospective priced evidence |
| CFB team markets | implemented | SHADOW_ONLY | prospective evidence and current team context |
| CFB player props | intentionally unsupported | UNAVAILABLE | prohibited by product scope; do not add |
| NHL team markets | implemented | SHADOW_ONLY | opening-season prospective evidence, goalie/personnel context |
| NHL SOG/points/assists/goals/saves | four-season artifacts + live research path implemented | VALIDATING | archived line calibration, same-day injuries/scratches, starting goalies, prospective prices/CLV |
| NHL PP points/blocks | odds discovery only | UNAVAILABLE model | validated historical/live feature source |
| NBA team markets | registry/training/refresh architecture implemented; automated artifact job active | RESEARCH ARTIFACT PENDING | workflow verification, current context, prospective market-relative evidence |
| NBA player core/combo props | causal history capture/training + distribution/joint architecture + odds discovery implemented | RESEARCH ARTIFACT PENDING | workflow verification, current rotation/injury inputs, prospective priced evidence |
| NBA cross-player SGP dependence | not modeled | UNAVAILABLE | aligned joint team/player simulation and validation |

## Promotion policy

No model is promoted because a development task says "finish all models." Promotion
remains evidence-driven:

- team buckets require prospective model-vs-market Brier improvement, calibration,
  clean identity/input evidence and the reliability-layer sample gates;
- player buckets require held-out distribution support plus frozen prospective priced
  observations, calibration/ECE, CLV and clean data-health/identity evidence;
- current sportsbook market coverage never substitutes for a trained model;
- missing personnel, lineup, injury, starter, settlement or identity evidence fails closed.

## Immediate execution sequence

1. Re-run the five NHL player artifacts with the corrected seconds-based TOI role floor.
2. Add verified same-day NHL injuries/scratches and starting-goalie evidence, then freeze prospective prices.
3. Complete the automated NBA artifact job and inspect team/player diagnostics.
4. Add current NBA rotation/injury evidence and freeze prospective NBA forecasts.
5. Resolve NFL/MLB production player-provider authentication/data-rights or integrate a
   separately verified provider; do not enable PRODUCTION_VERIFIED on trial/401 data.
6. Continue team-model prospective validation without replacing champions that fail to
   show statistically credible improvement.

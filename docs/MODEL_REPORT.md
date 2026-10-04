# JABBAZI model report — September 22, 2026

## Real baseline runs

| Sport | Completed history rows | Decisive 2025 test games | Brier score | Log loss |
|---|---:|---:|---:|---:|
| MLB | 14,673 | 2,473 | 0.244544 | 0.681943 |
| NFL | 1,455 | 284 | 0.225322 | 0.642141 |

Lower Brier score and log loss are better. These are probability scores, not
betting ROI, win rate at a stated price, or a forecast of subscriber profits.

- Earlier seasons 2021–2023 initialize team strengths; 2024 selects parameters.
- 2025 is held out from parameter selection.
- Available completed 2026 results update the final research ratings only.
- Each sport has its own parameters and artifact; the source checksum is saved.
- College football has no real trained artifact or reported performance yet.

## Market comparison

NFL model and market were compared on the same **284 games**:

| Probability source | Brier | Log loss |
|---|---:|---:|
| NFL baseline | 0.225322 | 0.642141 |
| No-vig market diagnostic | 0.210906 | 0.606989 |

**The NFL baseline is worse on both measures.** The nflverse schedule prices
lack individual quote timestamps, so this is a diagnostic comparison rather
than a point-in-time betting simulation. No historical bet return is claimed.

MLB has **zero historical odds comparisons** in this results-only dataset.
College football has not been trained on real data in this package.
All artifacts remain **SHADOW_ONLY**.

## Data and validation details

- Sources: MLB Stats API schedules and nflverse/nfldata schedules. Results are
  from completed games starting before September 22, 2026 UTC. The history
  files retain source labels, download time and per-game identities.
- MLB's abstract Final status can also describe postponed records. The adapter
  requires the completed-game code. Suspended/resumed games are excluded so a
  later final score cannot leak into the original date. Franchise names are
  normalized for the Athletics and Cleveland.
- NFL kickoff times are converted from Eastern time, including daylight-saving
  rules. Neutral venues are explicit. Ties update ratings with 0.5 and are
  excluded from binary scoring; the baseline is a decisive-outcome model, not
  a separate model of draw probability.
- Historical updates wait two UTC date boundaries after the start, giving a
  24–48-hour result delay. This conservatively avoids overnight overlap but
  is not a substitute for exact completion/availability timestamps.
- Same-day games cannot update one another's pregame predictions. Post-holdout
  games cannot change tuning or test predictions.
- Historical paired comparisons use identical game subsets. A separate
  timestamp-verified comparison counts only odds strictly before kickoff.
  This build has zero such timestamp-verified comparisons.
- The 0.05 uncertainty setting is an uncalibrated research setting, not a
  confidence interval. Models remain unapproved regardless of it.
- New code always keeps baseline outputs out of BET_NOW. Venue uncertainty,
  stale artifacts and unknown teams suppress estimates rather than invent them.
- No independent reviewer has approved these models. Starter, lineup, injury,
  weather, player and possession features are not yet in these Elo baselines.
- Reported results do not establish significance. Avoid tuning further models
  against this already-viewed 2025 test; retain an untouched evaluation period
  and collect prospective paper-trading observations.

## Software verification

The starter milestone had **45 local tests passed**. The current verification
record is in `IMPLEMENTATION_STATUS.md`. Starter coverage includes scanner/API access
checks, correct league routing behavior, time ordering, paired comparisons,
ties, postponed/suspended filtering, private-role overwrites, stale-alert
suppression, duplicate sends and ambiguous network failures.

A regression test also covers the scanner's closed-ledger bug. Previously,
the service closed its database before computing returned actions. Actions
are now built once while the ledger is open.

The Discord setup command was run in offline-plan mode. Discord API writes,
real webhook delivery, Whop billing, and Docker/cloud deployment have not been
executed. CFB response parsing has fixture tests but no authenticated live test.
There was an upstream test-client deprecation warning; no test failed.

## Reproduction

Use the preserved starter's `scanner/data/*_history.json` research snapshots, or
the history and `train-baseline` commands in README.md. Raw data and artifacts
are deliberately not committed in this repository. Test with Python 3.12 and the declared
API dependencies. Re-running training changes the training timestamp but
retains deterministic parameters and scores for unchanged data.

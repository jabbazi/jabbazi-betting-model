# NFL/MLB model improvement results — September 23, 2026

The MLB moneyline challenger improved the saved 2025 diagnostic. The NFL
challenger did not. Neither qualifies for production betting approval, and the
live scanner still uses its existing score-distribution models.

| 2025 diagnostic | NFL | MLB |
|---|---:|---:|
| Decisive games compared | 284 | 2,473 |
| Existing score-model Brier | 0.223282 | 0.247026 |
| Challenger Brier | 0.224518 | 0.244832 |
| Existing score-model log loss | 0.635409 | 0.687039 |
| Challenger log loss | 0.637923 | 0.682580 |
| Challenger calibration gap | 0.052237 | 0.023589 |
| Challenger AUC | 0.676585 | 0.564610 |
| Paired market Brier | 0.210906 | unavailable |

Lower Brier/log loss is better. MLB's Brier improvement is approximately 0.89%
relative to the existing model; that is **not ROI or probability edge**. Its paired
Brier difference is -0.002194, with a descriptive weekly-bootstrap interval
[-0.004362, -0.000261]. NFL's difference is +0.001236, interval
[-0.005979, +0.007797]. NFL still trails the paired market. MLB has no matched
historical market prices, so market superiority cannot be evaluated.

Both sports selected form + lagged Elo with C=0.1 using 2023 log loss from six
predefined candidates. All candidates and their metrics are retained. Logistic
calibration was fitted only on 2024. The uncalibrated predictions actually scored
slightly better on 2025 for both sports; those metrics are retained too, but we
did not switch to them after looking at 2025. This result illustrates that
calibration must be evaluated rather than assumed to help.

## What was built and run

- Reusable chronological moneyline experiment for NFL and MLB with finite feature
  ablation, train-only scaling, separate selection/calibration/diagnostic seasons,
  explicit ties, paired baselines, AUC, reliability and weekly bootstrap reports.
- Saved fitted coefficients, all diagnostic prediction rows and reproducibility
  hashes/package versions. No raw provider downloads or credentials are published.
- Five regression tests verify future/same-day exclusion, 2026 exclusion, split
  guards, duplicate/tie handling, paired comparison counts/direction, diagnostic
  label isolation from selection/fitting, provenance and artifact replay.
- Full local suite: **267 passed**, including the new tests. PostgreSQL-specific
  checks are not part of that local count. One existing discord.py `audioop`
  deprecation warning remains.
- GitHub CI passed for code commit `81abfc0276f4ad09b53c74012e4b90724dc6902b`:
  runs `35919099160` and `35919094709` both succeeded. The PostgreSQL-enabled suite
  reported **281 passed**. Ruff, authenticated API/container smoke, database
  backup/restore and database-outage checks also passed.
- The private scanner workflow now requests cloud model results plus current
  verified injuries, starters, lineups, weather and prices, with citations and
  explicit source/market coverage. It preserves shadow, stale-price and $0-stake
  states and does not invent probabilities for unsupported markets.
- A separate offline workflow trial using synthetic recorded scan/news evidence
  correctly withheld a pitcher-change candidate, kept a stale NFL quote stale,
  retained $0 stakes and declined an unsupported parlay. This is a simulated
  workflow test, not a new live scan or proof that an existing phone chat reloaded.

Local protocol/code was committed before the real-data run (`7e74a94`). These
are already-inspected 2025 development diagnostics, not an untouched holdout.
31 NFL and 2,340 MLB games from 2026 were excluded from every experiment stage.
This does not claim that no other project work has ever seen 2026 results.

## Reproduce

Install the repository research dependencies, then run for each sport:

```bash
python -m jabazi.research.moneyline_challenger nfl /path/to/nfl_history.json \
  /path/to/nfl-output --score-artifact src/jabazi/models/artifacts/nfl_scores.json
python -m jabazi.research.moneyline_challenger mlb /path/to/mlb_history.json \
  /path/to/mlb-output --score-artifact src/jabazi/models/artifacts/mlb_scores.json
```

Use the exact historical files identified by report checksums. A newer download
changes the source and must not silently be compared to a different artifact.

## Next model work and actual blockers

1. NFL: obtain point-in-time QB availability, opponent-adjusted EPA/success rate,
   and injury/usage features. Test each addition with a frozen protocol. More
   score-only tuning on the same viewed season will not establish an edge.
2. MLB: test the promising moneyline challenger prospectively and add licensed
   historical starting-pitcher/lineup/bullpen data with availability timestamps.
   The moneyline improvement does not validate run lines, totals or props.
3. Both: confirm historical odds entitlement and commercial modeling/derived
   display rights; obtain actual offered-at and closing-at quotes. Historical
   prices with unknown observation times cannot support an execution backtest.
4. Freeze candidates before collecting a new forward sample. Check calibration,
   paired market scores, actual execution/CLV, ROI, drawdown and effective sample
   size. Use a reviewed promotion process; do not edit SHADOW_ONLY to bypass it.
5. Player props and anytime TD remain separate, untrained targets. Admitted
   licensed player logs, participation/usage and decision-time injuries are needed.

No extra data was purchased, no new provider login was used, no wagers were placed,
and no public Discord messages were sent. The existing owner-only cloud scanner
and deployed model versions were preserved.

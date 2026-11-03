# NFL anytime-TD reliability pass — September 28, 2026

## Measured comparison

4,210 matched player/game predictions across 271 games in calendar 2025. Fit: pre-2024; calibration: 2024. All data through 2025 only. Already-examined retrospective period; not prospective proof.

| Model | Brier (lower better) | Log loss | ECE |
|---|---:|---:|---:|
| baseline | 0.166671 | 0.511973 | 0.011100 |
| challenger_raw | 0.166832 | 0.508934 | 0.024575 |
| challenger_calibrated | 0.166676 | 0.508721 | 0.021731 |

The calibrated challenger did not establish an improvement. Equal-game Brier difference versus baseline: +0.000045; game-cluster bootstrap 95% interval [-0.001290, +0.001243]. Log loss improved slightly; calibration error worsened. The live champion is retained.

## What changed

- New monotone calibration code uses one positive-side probability and complements it for Yes/No or Over/Under. Newly trained artifacts use schema/version 0.3 with linear isotonic interpolation matching scikit-learn.
- Existing positive-side predictions retain their exact legacy step mapping and version. Legacy calibrated negative-side predictions are unavailable until their mapping has been refit/validated; frozen history is never rewritten.
- Count distributions now distinguish a strict Under win from equality. The scanner rejects whole-number player lines because its scalar EV contract does not price push payouts. No integer line is silently treated as a no-push wager.
- Invalid thresholds, mislabeled binary thresholds, malformed scalers, and non-monotone calibration fail closed. One game cannot cross training/calibration partitions through different player decision timestamps.
- Trained a separate opportunity-based logistic ATD challenger using prior carries, targets, separate rushing/receiving TDs, shares, team and opponent scoring, position and season/appearance context. Calibrated on a later separate period. No fabricated personnel or red-zone inputs.

## Calibration: frozen baseline versus calibrated challenger

| Probability bucket | Baseline n / mean / observed | Challenger n / mean / observed |
|---|---|---|
| 0%–5% | 71 / 1.5% / 4.2% | 14 / 1.9% / 7.1% |
| 5%–10% | 605 / 9.2% / 9.1% | 136 / 8.7% / 8.1% |
| 10%–15% | 796 / 12.7% / 14.4% | 838 / 12.9% / 10.4% |
| 15%–20% | 420 / 18.5% / 18.6% | 1041 / 17.4% / 17.0% |
| 20%–25% | 734 / 23.0% / 23.7% | 688 / 22.3% / 24.3% |
| 25%–30% | 242 / 25.8% / 26.4% | 518 / 27.4% / 31.5% |
| 30%–35% | 616 / 31.6% / 32.1% | 326 / 32.4% / 31.9% |
| 35%–40% | 254 / 38.6% / 35.0% | 212 / 37.2% / 36.3% |
| 40%–45% | — | 137 / 42.5% / 44.5% |
| 45%–50% | 407 / 46.5% / 44.0% | 106 / 47.3% / 42.5% |
| 50%–55% | 8 / 50.0% / 50.0% | 77 / 52.2% / 44.2% |
| 55%–60% | — | 35 / 57.3% / 65.7% |
| 60%–65% | — | 27 / 62.6% / 48.1% |
| 65%–70% | 57 / 68.8% / 66.7% | 21 / 66.9% / 52.4% |
| 70%–75% | — | 23 / 72.5% / 65.2% |
| 75%–80% | — | 9 / 77.2% / 66.7% |
| 80%–85% | — | 2 / 83.4% / 100.0% |
| 85%–100% | — | — |

Full reliability intervals, position-specific metrics and paired comparisons are in [report.json](report.json). Frozen predictions include the exact feature snapshots. The offline challenger is [artifact.json](artifact.json); it is not registered with the cloud service.

## Remaining requirements

- Current live SportsDataIO NFL projection endpoint still returns HTTP 401. Confirm paid production access to `nfl/projections/json/PlayerGameProjectionStatsByWeek` and the associated role/injury feed. A successful HTTP response alone does not verify production authenticity.
- Add and validate pregame participation, snap/route role, goal-line carries, red-zone/end-zone targets, and current team scoring context. Current model is mainly lagged usage and scoring history.
- Reconcile sportsbook anytime-TD settlement with the current rushing/receiving-only training target, including return/recovery TDs. Historical stat-archive presence is not a complete pregame roster; missing non-participants and zero-opportunity players can bias calibration.
- Collect frozen prospective forecasts paired with actual contemporaneous prices and closing quotes. There is no demonstrated priced player-model edge or prospective ATD evidence yet.

No production model is promoted; no player feeds are asserted to be licensed/verified; no Discord messages or wagers are sent. No database migration. API/tool schemas are preserved.

## Reproduction

```bash
python -m jabazi.research.nfl_atd_experiment --raw-dir /path/to/preserved-inputs --output /tmp/atd-report
python -m pytest -q
```

Raw source captures are preserved separately with source hashes; they are not duplicated in this public repository. Source attribution: nflverse contributors; see the pinned [capture manifest](../nfl-player-props/request.json). Historical timestamps use a two-day availability proxy rather than original observation receipts.

## Deployment

This file records source changes and measured results. Deployment is verified separately against the actual API and worker commit; merging this research report does not register or promote its challenger.

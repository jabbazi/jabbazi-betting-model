# NBA team recovery — October 21, 2026

Research only. No production approval, no official wager generation.

The live NBA refresh failed with `Completed game coverage unavailable` after
opening-night finals arrived but before the two-UTC-date availability delay had
expired. Refresh now preserves a research artifact, exposes
`WAITING_FOR_ELIGIBLE_HISTORY`, and retains all inference freshness/sample gates.
The availability timestamp is not a promise of forecast eligibility: each team
still needs eight eligible games and recent history.

The previous bundled history contained 41 team labels including exhibition and
All-Star teams. Capture and refresh now admit only the 30 canonical NBA franchises
and normalize LA Clippers to Los Angeles Clippers. Rebuilt the team artifact from
4,923 completed games across ending seasons 2023–2026. Nine rows from the prior
4,932-game capture are excluded. Player artifacts were not retrained or approved.

Reproduction:

```
python tools/capture_nba_sportsdataverse.py --team-only --output /tmp/nba-history
python -m jabazi.research.train_scores nba /tmp/nba-history/nba_team_history.json /tmp/nba-model
```

The attached receipts record source URLs, response hashes and retrieval times.
The report retains fit, residual-calibration and diagnostic splits. The 2025
season was previously inspected and is NOT an untouched final holdout. Spread
and total diagnostics use fixed thresholds, not archived tradable lines. There
are no paired timestamp-verified market prices or demonstrated betting profits.

Provider diagnostics now expose allowlisted HTTP codes without URLs, keys or
response bodies. Live verification of the first recovery release confirmed
HTTP 401 across all five sports; credential/subscription/quota investigation is
still required. A healthy server is not evidence of a healthy odds feed.
Worker health now reflects failed closing collection rather than just a running
process. New model versions refresh without waiting for the old six-hour window.

Known outstanding issues: odds provider access, repeated Discord status-panel
404s, opening-season forecast coverage, audited injury/rotation inputs and frozen
prospective market-baseline validation. Do not relax inference gates to hide them.

## October 21 follow-up: early-season diagnostics and transport recovery

The decay/shrinkage candidate is NOT promoted. On 1,231 previously inspected diagnostic games, moneyline Brier improved from 0.21119 to 0.20989 but totals worsened from 0.22712 to 0.22943. October (75 games) results are mixed. See early-season-diagnostics.json. These samples are not untouched prospective evidence; fixed-line diagnostics do not demonstrate executable profitability. No roster-change adjustment has been validated.

Live NBA refresh now fetches preceding regular-season history after current-season results become eligible, matching the existing training carryover behavior. It retains the per-team seven-day freshness gate, minimum sample requirement, strict label availability, and SHADOW_ONLY status. A team with no recent eligible result remains unavailable. This is a training/live consistency repair, not approval of a new early-season model.

Odds requests use a durable credential-scoped circuit with bounded backoff, allowlisted failure codes and safe timestamps. A fresh authenticated scan on October 21 failed before prices were obtained; odds restoration remains unverified. Discord diagnostics identify GET /channels/1554622841201365072 returning 404 after guild/owner checks; no alternate destination was chosen.

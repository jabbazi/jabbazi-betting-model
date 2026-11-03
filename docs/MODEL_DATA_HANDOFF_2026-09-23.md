# NFL/MLB data build handoff — September 23, 2026

Two bounded public-source captures now work against real files in GitHub Actions.
This is research infrastructure progress, not a new production model release.

| Work actually run | Verified result | What it does not establish |
|---|---|---|
| NFL nflverse capture | 1,456 completed games; 2,912 team-game snapshots; efficiency features available for 16 upcoming captured events | Historical receipt-time availability, advanced model probabilities or market superiority |
| MLB Retrosheet capture | 106,837 pitching appearances across 12,361 games in 2021–2025 | Pregame starter knowledge, complete workload features, current 2026 coverage or prop probabilities |
| Automated verification | 315 tests passed; API/container, PostgreSQL restore and outage checks passed | Calibration, ROI/CLV, cloud deployment or paid-picks readiness |

See the full [NFL capture evidence](experiments/nfl-context-capture/README.md) and
[MLB staging evidence](experiments/mlb-history-capture/README.md). Both preserve
actual receipt times, source checksums and raw archives; missing evidence is not
filled with invented timestamps. MLB rows are staging only. NFL strict historical
training-ready rows remain zero because these files were first captured now.

## Code and verification

- NFL capture: code `076d1a38d621ddf48ed2168541d22476680de969`,
  [successful source run](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35924197502).
- MLB capture and final code: `21a791d27dee3e68720f752bb51cb39846d04b08`,
  [successful source run](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35925101387).
- Final [CI run 35925105287](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35925105287):
  **315 passed**, one existing discord.py audioop deprecation warning; Ruff passed.
  Unauthenticated API access returned 401; missing provider failed closed; CI
  betting remained disabled. Container startup, worker heartbeat, audit-evidence
  preservation through database backup/restore, and database-outage behavior passed.
- Ten new capture regression tests cover final-score mismatch, digest/size guards,
  fixed source requests, conservative completion bounds, historical exclusion,
  MLB statistic variants, missing counts, duplicate identities, wrong-season dates,
  negative counts and doubleheader identity. Fixtures test code, not prediction skill.

All code remains in [draft PR #2](https://github.com/jabbazi/jabbazi-betting-model/pull/2).
No merge into the production branch, Render model rollout, continuous collector,
Discord post/change, provider purchase or wager occurred in this increment.
The prior moneyline experiment remains available; neither its MLB improvement nor
these new captures validate the requested full-game, derivative or player models.

## Remaining dependencies and owner input

No new login was required for either public capture. GitHub access worked.
Do not send provider keys through chat or Discord.

1. **Existing odds account:** verify historical snapshot and prop-history
   entitlement, including offered-at/closing-at timestamps and market identity.
   Current odds access does not prove these permissions. This audit did not inspect
   the private account's billing or entitlement settings.
2. **Pregame context:** obtain archived NFL QB/injury/usage and MLB confirmed
   starter/lineup revisions. For current MLB operation, add current pitcher logs,
   pitch counts and verified IDs. Preserve original observations going forward.
3. **Commercial provider permission:** nflverse and Retrosheet attribution is
   recorded in their capture documents. That does not cover a different paid feed.
   SportsDataIO is a possible combined provider; its commercial modeling/derived
   display rights and price require a specific agreement. No quote was requested.
   Approval is needed only after scope and actual price are concrete; no purchase
   or permission request is implied by naming a provider.
4. **Durable archives:** Actions artifacts expire December 22, 2026. Raw captures
   and receipts must be copied to durable research storage before then. This run
   verified their upload and metadata; local artifact download returned HTTP 403,
   so ZIP contents were not independently downloaded/replayed here.
5. **Validation:** verify crosswalks and chronology, freeze feature ablations,
   compare on identical games against the market, and collect an unseen forward
   sample. The already-viewed 2025 diagnostic is not a fresh final holdout. Train
   separate player usage/distribution targets before labeling props supported.

The new captures cannot support the full advanced experiment under the current
strict availability contract. Retrospective reconstruction, if pursued, needs a
separate declared protocol and sensitivity checks, with no claim of original
historical data availability. Do not change SHADOW_ONLY as a substitute for this.

## Discord recommendations for the owner

Based on saved setup documents, not a fresh live-server inspection:

- Add or designate **pick-updates** for changed prices, scratches, cancellations
  and withdrawn picks, linked by original pick ID. Keep main-card and sprinkle
  records distinct and retain the original post.
- Use the existing planned **public-results** channel for complete win/loss/push
  recaps, units and corrections; avoid adding a duplicate results channel.

Keep model diagnostics and scanner controls owner-only. No additional bot is
needed for either recommendation. These are recommendations only, not published
Discord content or verified new channels.

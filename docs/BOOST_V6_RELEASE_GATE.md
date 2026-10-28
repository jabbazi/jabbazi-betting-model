# JABBAZI V6 Boost — Release Gate and Execution Handoff

Status: **RESEARCH ONLY / NO PRODUCTION APPROVAL**. This document does not
authorize promotion, merge, deployment, automated wagers or public picks.

## Existing production protection
- Keep the deployed Research API and Worker on their current proven commit
  until final live acceptance, not merely a passing mocked workflow.
- Keep the normal SCAN EVERYTHING flow separate from BEST PLAY FOR THIS BOOST.
- Preserve Discord VIP permissions, database policies, secrets, and existing
  auth/entitlement behavior. Never print paid provider keys or open the
  database IP allowlist to bypass its private-network configuration.

## What is now implemented on PR #80
- Vendor sport-isolated NBA/NFL/NHL prop route and paginated price retrieval.
- Fail-closed paid-odds identity audit with raw, accepted, duplicate, invalid,
  cross-game, page and game counts. Anomalies are PARTIAL, never FULL.
- Research-only sport-slate discovery on a specified vendor calendar date.
  Requires complete game pagination and scheduled lifecycle; a game cap stops
  the scan rather than truncating without disclosure.
- Research-only eligibility / freshness filtering and bounded 2–4-leg
  combinations. No parlay price is fabricated, no correlated marginal
  probabilities are multiplied, and no wager can be approved from a
  structure alone.
- Mock-provider and unit regression tests; inspect final-head Actions jobs.

## Independent acceptance evidence required

1. **Provider**: From an authorized runtime, make paid authenticated
   NBA, NFL and NHL queries for known current game IDs; record status, UTC
   observation, eligible game counts, pages, raw/accepted/duplicate/rejected
   prop rows, exact request scope and quota failure handling. Do not print
   licensed rows, personal player IDs, or credentials. BALLDONTLIE prop
   endpoints return sportsbook prices, not paid model probabilities.
2. **Models**: Join event/player/market IDs point-in-time to existing
   registries. Train NBA and NHL joint models on genuine historical
   observations with chronological separation, baselines, uncertainty and
   independent prospective evaluation. Keep unvalidated artifacts in
   RESEARCH_ONLY and disallow inferred SGP joint probabilities.
3. **Promo and odds**: Verify token state, game/market rules, min/max legs,
   minimum preboost odds, stake/profit caps, expiry and availability from the
   actual sportsbook. Obtain exact combined executable quotes for eligible
   structures. Never compute SGP prices by multiplication.
4. **Valuation**: Permit a selection only after all prior gates,
   fresh model provenance, conservative joint EV and exposure/risk limits.
   Missing evidence means PASS; 1u=$50 subject to actual caps, not a
   prescribed wager.
5. **Integration**: Add the dedicated workflow to the existing VIP and
   Discord surfaces with role checks and full path tests. Regression-test
   the broad scanner separately, including its quota accounting.
6. **Release**: Confirm fully green Actions on the final PR commit, run
   staging/live-provider acceptance in an authorized runtime, review the
   diff, then and only then merge/deploy the existing Render services.
   Compare deployed commits and verify health, VIP/Discord handoff,
   paid endpoints and model calibration after deployment.

## Unresolved access blockers
The current tooling supports GitHub code edits, CI reads and Render deploy
metadata/logs. It does not provide an authenticated Render exec shell or
private-network database access for prospective NBA/NHL calibration and
live paid-provider acceptance. **Do not label the release complete** until
those checks can be performed and their concrete results recorded.

Source: Issue #79 and draft PR #80 in jabbazi/jabbazi-betting-model.

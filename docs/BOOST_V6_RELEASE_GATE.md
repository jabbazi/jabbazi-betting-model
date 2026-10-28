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

## Reproducible single-sport paid access evidence

An operator with existing authorized Render shell access can run the
read-only tool without copying keys, making secret changes, merging or
deploying. Run one sport at a time, on a verified upcoming vendor calendar
date; examples below show a placeholder date, **not completed evidence**:

```bash
python tools/boost_live_acceptance.py --sport NBA --date YYYY-MM-DD --request-budget 36
python tools/boost_live_acceptance.py --sport NFL --date YYYY-MM-DD --request-budget 36
python tools/boost_live_acceptance.py --sport NHL --date YYYY-MM-DD --request-budget 36
```

Specify `--game-id` and `--market` only when the particular promotion
restricts those choices. Default query covers all eligible scheduled games
within a 25-game cap. The probe stops rather than silently truncating larger
slates, handles one-response live prop endpoints, follows game-page cursors,
and avoids emitting licensed odds, player IDs, secrets or invented probabilities.

Exit code 0 means the provider returned a complete bounded set of requests,
**not** that available sportsbook odds, betting predictions or calibration
passed. Exit code 1 means incomplete/failed quote coverage; 2 means no secret
was configured. Inspect the aggregate JSON, timestamp, error codes and
current service commit. For full release, attach actual three-sport outputs
and independently validated NBA/NHL joint-model and sportsbook SGP evidence.
Running this only in GitHub Actions without the actual Render service key
does not satisfy live acceptance.

The tool does not place bets or send Discord alerts, and the existing broad
scanner is not called.

## One-run three-sport live acceptance (operator-only)

A new **read-only** command collects a bounded NBA/NFL/NHL coverage matrix
from an authorized runtime with the already-configured BALLDONTLIE key.
**The current production image does NOT include this feature-branch script**:
the existing Render Shell page opens its running production commit, not PR #80.
For acceptance, securely use a checked-out copy of the exact PR commit in an
isolated authorized runtime with the service's existing secret available.
Do not merge/deploy unverified code just to gain access to the script.
Render supports isolated ephemeral shell instances, but the available hosted
connector cannot open one or copy this private feature branch into it.
Document the executed commit with the output:

```bash
python -m tools.boost_live_acceptance_matrix --nba-date YYYY-MM-DD --nfl-date YYYY-MM-DD --nhl-date YYYY-MM-DD --max-games 25 --request-budget 90
```

Do not run this from a public build, print the provider secret, modify Render
networking, or treat a mocked Actions workflow as live provider verification.
Use the actual upcoming game date **separately for each sport**. NFL
game records have UTC timestamps (which may roll into Monday UTC for
Sunday-night Eastern games); the collector validates them against the
game's Eastern calendar day. Do not force a Tuesday NFL date just
because NBA or NHL plays Tuesday. A common `--date YYYY-MM-DD`
remains available for explicit same-day audits, but a sport with no
game must return NO_ELIGIBLE_GAMES, not successful coverage.

This checks
eligible scheduled games for all three sports with one shared request budget,
stops on subscription/rate-limit exhaustion, and reports only sanitized
aggregate per-sport counts and observation times. If there is no eligible
game or no valid available prop row, the matrix is **NOT COMPLETE**.

The matrix deliberately reports `production_approved=false` and
`betting_decision=PASS` **even if the three paid feeds responded**.
Actual NBA/NHL validated joint probabilities, independent prospective
outcomes, genuine executable sportsbook SGP quotes, and VIP/Discord
integration are independent release gates. A nonzero exit code means
the provider coverage evidence itself is insufficient, not that a sports
bet is a loss. Keep all raw credential/licensed data private.

This command has not been executed from a Render shell by the hosted
connector and does not prove live acceptance by itself.

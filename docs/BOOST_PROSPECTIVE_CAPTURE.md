# JABBAZI V6 NBA/NHL prospective joint-ticket archive

**Status: NOT DEPLOYED / RESEARCH ONLY.** The new library is not called by the
live scanner, VIP app, Discord worker, or a scheduler. It does not generate
probabilities, obtain sportsbook SGP quotes, predict outcomes, place bets or
approve model promotion. It must only be invoked from a trusted, authorized
private runtime after genuinely sourced forecasts and bookmaker evidence
already exist.

## 1. Storage and safety

This path reuses the existing `platform_events` immutable event store through
`JABBAZI_PLATFORM_DATABASE_URL`, without a second database, network-policy
change, migration, new secret, or data export. Records use the distinct
`boost_joint_forecast` / `boost_joint_result` kinds. Writes are
transactionally append-only; an attempt to revise a frozen identity with
different evidence is rejected. Only exact, independently versioned NBA/NHL
2–4 leg player-ticket research is accepted. No bets are placed or Discord
messages posted.

The capture source is **not authenticated merely because a JSON provider name,
snapshot hash or market probability is present**. The operator must verify
source rights and receipts against independent real records. Synthetic unit
fixtures are strictly excluded from production.

## 2. Freeze genuinely generated pregame evidence

Prepare a private JSON document containing:

- `sport`: `basketball_nba` or `icehockey_nhl`; `event_id`,
  `ticket_id`, `model_version`, `split: "prospective"`.
- `trained_through`, `test_start`, `prospective_start`, `starts_at`,
  as timezone-aware instants establishing the fixed chronology.
- `joint_probability`: the real fitted model's already-computed exact
  **joint** ticket probability (not multiplied marginal probabilities).
- `legs`: 2–4 distinct entries containing `leg_id`, `player_id`,
  `market`, `side` (`over`, `under`, `yes`, or `no`), and numeric
  `line` for over/under; yes/no uses null.
- `model_source`: `provider`, `observed_at`, and a protected `payload`
  with the same `event_id`, `ticket_id`, `model_version`,
  `joint_probability`, ordered `leg_ids`, and
  `features_available_at`. The source must truly substantiate the
  versioned fitted model and its frozen pregame features.
- Optionally `market_source`: `provider`, `observed_at`, and
  `payload` with `baseline_kind:
  "independently_quoted_combined_ticket"`, exact `event_id`,
  `ticket_id`, ordered `leg_ids`, a nonempty sportsbook `book`,
  and independently verified `no_vig_probability`. **Do not invent a
  de-vigged joint market probability from a single SGP quote or the product
  of the legs.** Without genuine market baseline evidence, the forecast may
  still be frozen for research but is **excluded** from the strict
  market-baseline audit.

Write evidence privately, then run in an approved isolated checkout on the
feature commit with its existing configured platform DB access:

```bash
python -m tools.boost_joint_capture freeze --input /private/pregame-ticket.json --commit-evidence
```

Freeze uses the runtime-observed current UTC time for both `predicted_at`
and `forecast_frozen_at`. Model and market source snapshots must be
recent (10 minutes) and the game must not have started. The result includes
only the deterministic `forecast_id` and whether the append occurred.
**Do not generate source snapshots retroactively after kickoff.**

## 3. Reconcile after authoritative game final

Only after the event has finished, prepare a different private result
document with `forecast_id`, `leg_results` matching **every** original
`leg_id` / `player_id` / `market`, and `result_source` containing
`provider`, `observed_at`, and `payload`. The source payload must
identify the same `event_id`, `ticket_id`, `forecast_id`, the exact
`leg_results`, `event_status: "final"`, and a timezone-aware
`completed_at` later than game start and not later than source observation.
Each leg must have `status: "final"` and nonnegative `observed_value`,
or a documented `void`, `dnp`, `canceled`, or `push` status.

```bash
python -m tools.boost_joint_capture settle --input /private/resolved-ticket.json --commit-evidence
```

The capture never trusts a supplied ticket win flag. It derives a binary
outcome from **every verified final leg**. Pushes, voids, DNP and canceled
legs are excluded from binary calibration; originals stay archived without
revision. This is a research derivation, not an official sportsbook settlement
determination. An independent settlement-rules audit remains required.

## 4. Readiness audit and release gates

```bash
python -m tools.boost_joint_capture audit
```

The output contains only aggregate per-sport metrics and event counts; it
does not print raw player IDs, leg details or licensed data. Only fully
resolved tickets with a claimed independently sourced exact combined
market baseline enter the downstream strict audit. That audit checks
chronology, event leakage, fixed train cutoff, independent-game-weighted
Brier/log loss and market comparison, and **always** reports
`approved_for_betting=false`. Snapshot SHA values are computed from
actual supplied source objects but do not authenticate the external records.

What is still required before production:
genuine prospective NBA/NHL joint model forecasts and final outcomes,
audit of authentic source receipts and no-vig combined market baselines,
independent event counts and expert calibration review, plus paid NBA/NFL/NHL
feed acceptance, bookmaker quote freshness and VIP/Discord end-to-end checks.

There is no live data-capture job, no automated source mapper and no
approved NBA/NHL joint model yet. PR #80 stays draft until those
requirements are evidenced. Do not deploy for the sake of accumulating
unverified or fabricated samples.

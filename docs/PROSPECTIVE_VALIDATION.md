# Prospective evidence collection

This upgrade starts collecting future evidence; it cannot create past prospective
results. Existing NFL/MLB/CFB model versions and cash permissions are unchanged.

## Fixed sampling policy

`first-fresh-home-or-over-per-game-bucket-v1` admits one observation for each
sport, schedule game ID, model version and market family. Sides use the home team;
game totals use Over; team totals use home-team Over. The first available fresh
line wins atomically. Later price changes, repeated scans, opposite selections
and the remaining alternate ladder do not add samples. This first-seen line
policy is not an optimized bet-selection strategy. Families share games, so their
sample counts must not be added together as independent observations.

Freeze time is server time, strictly before kickoff. Quote and observation ages
must both be 0–120 seconds. Required evidence includes code commit, dataset hash,
feature schema, schedule ID, feature snapshot and quote IDs. Integer non-ML lines
with model push mass are excluded. Moneyline metrics are conditional on no tie;
actual ties and pushes are excluded and counted separately. No historical
prediction is imported as a new prospective observation.

## Result receipts and grading

The existing six-hour NFL/MLB/CFB refresh archives immutable result receipts from
its already-fetched schedule data, with source hash and first observation time.
Only results past the existing conservative availability delay (two UTC date
boundaries) and within 30 days are imported. CFBD refresh still requires the
configured credential. Unsupported, suspended and incomplete games are excluded
by existing adapters. A long outage beyond this window needs an explicit backfill.

The report matches sport, schedule ID, home/away identities and kickoff within
60 seconds. Reschedules and identity conflicts stay ungraded. Research score
labels do not certify sportsbook settlement rules, action/listed-pitcher rules,
postponement terms, cancellations or ticket profit. No placed bet is altered.

Corrections are additional immutable result receipts, never edits. Reports use
the latest receipt and can change accordingly; the original receipts and frozen
forecasts remain available for audit. Reports are live views, not signed period
snapshots. Querying streams all relevant evidence rather than silently truncating
at 1,000 records. Long-term materialized report caching remains future work.

## Reports and restrictions

Owner-authenticated `GET /v1/research/prospective-validation` returns counts,
pending results, identity failures, pushes, Brier score, log loss and same-quote
no-vig market metrics. Five-point calibration buckets include sample counts,
mean predicted probability, observed hit rate and 95% Wilson intervals. Intervals
describe binomial sampling uncertainty, not parameter or cross-game dependence.

Existing `get_model_status` gains per-market frozen, pending and graded counts.
Its stage remains SHADOW_ONLY. No automatic promotion, calibrated probability,
CLV series, ROI claim or paid recommendation is manufactured by this collector.
Promotion still requires independent evidence and data-integrity clearance;
verified QB/starter/lineup inputs and bucket-level model validation remain open.

Persistence uses the existing append-only SQL event schema:
`prospective_forecast` and `prospective_result`. No migration or new paid service.

## Deployment

Deploy the tested commit to BOTH existing Render API and worker. The scanner will
freeze forecasts on its next successful scan; result capture occurs on the next
due six-hour refresh. Verify `get_model_status` frozen counts before claiming
collection is active. Graded counts remain zero until actual games finish and
results pass the availability delay. Existing scans remain owner-only.

## Verified rollout — 2026-09-25

PR [#6](https://github.com/jabbazi/jabbazi-betting-model/pull/6) merged as
`f5fba4a179a6f0d9b1331be421e04974864514ba`. Both Render API and worker show this
commit as live. [CI run 36100274978](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/36100274978)
passed 364 tests including PostgreSQL, container startup, backup/restore and
outage checks; 350 tests passed locally.

Live liveness/readiness returned 200; unauthenticated access to the new validation
endpoint returned 401. The scheduled worker scan completed with 5 feeds, 4,408
quotes, 762 modeled candidates and no errors. Existing get_model_status verified
34 MLB, 90 NFL and 108 CFB frozen game/market forecasts (232 total, not 232
independent games). All graded counts are zero and all buckets remain SHADOW_ONLY.

The result-archive path is deployed and tested but was NOT_DUE on this run; no
live result-grading claim is made. CFBD credentials are still missing for ongoing
CFB refresh. See the [machine-readable deployment receipt](experiments/reliability-upgrade/prospective-deployment-verification.json).
The worker's heartbeat `completed_at` currently records loop start; the observed
log time, not that field, establishes scan completion for this receipt.

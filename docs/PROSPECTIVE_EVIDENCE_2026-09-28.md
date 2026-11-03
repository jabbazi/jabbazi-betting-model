# Player prospective evidence integrity

This release changes validation accounting, not fitted probabilities or model approval.

## Demonstrated risks fixed

- Repeated thresholds/players in a single event counted toward the same 500-row promotion requirement. Reports now expose distinct graded events and distinct CLV events. Production requires at least 500 events and 150 CLV events; limited-live requires 200 events. These are conservative placeholder policy thresholds, not scientifically optimized sample sizes.
- Unverified/research-only snapshots could enter performance metrics. Such records remain immutable but are counted as data-health failures and excluded from promotion metrics. Legacy records without explicit trust fields fail closed. Result identity failures also block promotion.
- A closing probability stored against a player's statistic lacked selection/line identity. Legacy unbound values no longer count as CLV. An optional `closing_quote` must carry matching sport, event_id, participant, market, selection, line, settlement_rules, a pregame observed_at after the forecast, source_checksum, and no_vig_probability. Settlement rules must match the forecast snapshot. Until that evidence exists, CLV remains unavailable.
- Refresh previously processed old artifact revisions and ignored evidence changes when sample count and stage were unchanged. It now streams the archive, evaluates the current artifact per sport/market only, and stores changed evidence as immutable revisions. Demotion and re-approval can recur without idempotency-key collisions.

## Reports

`sample_count` retains its prediction-row meaning for compatibility. `independent_event_count` explicitly counts events. `event_weighted_market_comparison` reports model-minus-market Brier difference, weighting each event equally, with a deterministic 400-replicate event bootstrap interval. This is descriptive uncertainty, not a guarantee or a substitute for time/season stability evaluation. Same-event players/thresholds never become independent bootstrap units. A single event receives no interval.

## Limitations and deployment

This does not train a new model, repair weak football features, validate commercial provider access, automatically capture exact closing prices, or complete the production database audit. No database migration is needed: new evidence/report fields are additive JSON. Existing closing probability inputs are preserved for audit but cannot support promotion without exact matching receipts. Deployment status and test results are recorded in the pull request after verification.

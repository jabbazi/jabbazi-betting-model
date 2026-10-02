# Same-game research engine v0.2

The scanner now screens bounded two-leg combinations from the deployed joint team-score and admitted NFL player models and exposes `evaluate_same_game_parlay` for 2–4 selected legs. This is a research engine, not a betting-approved SGP model.

## Integration

- Scan results: `event_market_coverage.same_game_parlays`, up to 12 candidates from at most 300 pairs and eight standard-market legs per event. Ordering is joint hit probability, **not EV**. Partial/unhealthy scans suppress candidates. Archived candidates are marked stale on retrieval.
- MCP tool: `evaluate_same_game_parlay`.
- Scoped authenticated POST: `/v1/chatgpt/same-game-parlay`.
- Model status: `same_game_engine` reports version and limitations.

Request `scan_id` and `leg_indexes` (zero-based across retained rows: `(page - 1) * 25 + row offset`). Only a healthy completed archived scan is accepted. Inference is rerun against the currently loaded model with its identity and freshness checks. No provider-credit calls occur.

First evaluate without an offer to obtain `candidate_id` and `settlement`. Then optionally supply `offer` with those exact values, a sportsbook, quote ID, decimal odds and timezone-aware `quoted_at`. This is an owner-supplied exact combined offer; it is not independently verified or executable. Separate straight-leg prices are never multiplied to fabricate a combined price. Quote and leg evidence must be at most 120 seconds old.

## Mathematics and settlement

NFL/MLB/CFB (and NBA only if its model loads and passes inference) use paired score residual scenarios from the existing model. NHL uses its weighted final-score grid, including the overtime/shootout deciding goal. All leg outcomes are evaluated on the **same** scores with the **same** weights. The engine returns joint and marginal probabilities, pairwise phi correlations, and an explicitly labeled independence diagnostic. The diagnostic is not used for pricing.

Markets: moneyline, spreads, totals, team totals and alternate variants. Integer lines or moneylines with modeled push/tie mass are rejected because a sportsbook-specific reduced-parlay payout is unavailable; ties are never silently dropped. Duplicate leg identities, different games, in-play events, stale data and unavailable model inputs fail closed.

The probability adjustment is the sum of existing leg policy haircuts (capped at one), subtracted from joint probability. It is **not** a calibrated SGP uncertainty interval. Raw and adjusted research ROI are calculated only for a bound, fresh combined offer with matching settlement. No payout or probability is a guarantee. Stakes remain null and cash influence and betting approval remain false in every result.

## NFL player correlations

The bundled `nfl-player-joint-ranks-0.1.0` artifact fits an empirical checkerboard copula to aligned residual probability ranks from the pinned nflverse capture. Marginal models were trained before 2024; dependence uses 2024, and 2025 is the held-out benchmark. Discrete probability atoms use independently seeded, reproducible jitter. Runtime combines that historical dependence with the current marginal probabilities, preserving the marginals and Fréchet bounds. Rank correlation describes standardized historical dependence, not the correlation of every possible betting threshold.

Six same-player role/market buckets improved joint Brier error over independence on the fixed over/over benchmark: WR/TE/RB receptions + receiving yards; RB carries + rushing yards; QB attempts + completions; QB passing yards + passing TDs. The QB–WR and QB–TE same-team passing/receiving buckets were measured but did **not** improve held-out Brier error, so they remain unavailable for ticket pricing. The complete report is in `docs/experiments/nfl-player-joint/report.json`, including adverse results. Admission based on this one holdout consumes it for model selection; it is not fresh prospective validation or proof of profitability.

Two NFL prop legs only. Each inference requires the verified player identity, position, availability and current features used by the marginal models, plus exact marginal model versions. Team identity is required for cross-player relationships. Models for mixed team/player tickets, three/four-player tickets, scoring props, MLB/NHL/NBA joint props remain unavailable. The NFL snapshot now retains verified depth-chart team identity for this check.

Training includes eligible player-game pairs but reports unique game counts separately; teammate pairs and repeated players are clustered, not extra independent prospective observations. Historical feature availability is reconstructed. Benchmark thresholds are fixed research lines, not archived sportsbook quotes. There are zero prospective SGP observations and no claim of statistical significance from a single-season Brier improvement. Pooled positional dependence is an assumption that can fail after role or usage changes.

Reproduce: capture `docs/experiments/nfl-player-joint/request.json` with `tools/capture_nfl_player_props.py`, then run `tools/train_player_joint.py --capture <capture-directory> --output src/jabazi/models/artifacts/nfl_player_joint.json`. This excludes the changing 2026 source; all 2021–2025 bytes were checked against the pinned hashes. No paid provider data was requested.

No automatic sportsbook quote feed, betting approval, bet placement or Discord publication is added.

Tests cover positive/negative dependence, impossible combinations, real score-model and NHL adapters, tie handling, alternate duplicate detection, quote binding and age, archived API inputs, schema/MCP integration, candidate expiry and preserved zero-stake behavior.

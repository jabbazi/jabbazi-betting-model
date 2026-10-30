# Pricing and research conventions

- Probability edge is model probability minus market probability, in probability
  points. Expected ROI is `p_win * decimal_odds + p_push - 1`. Expected profit
  is stake times expected ROI. These are separate fields.
- Fair decimal payout with pushes is `(1 - p_push) / p_win`. Minimum acceptable
  payout is `(1 + required_ROI - p_push) / adjusted_p_win`. Higher decimal payouts
  are better. Legacy `maximum_playable_decimal` means the minimum acceptable
  decimal payout, not a ceiling on decimal odds.
- American fair odds are rounded for display. Decisions use unrounded decimal
  prices. Invalid, nonfinite, or suspended prices are rejected.
- Book hold is implied-probability sum minus one (overround), not realized revenue.
  Proportional no-vig requires a complete, mutually exclusive outcome set.
  Two-way push markets express conditional probabilities given no push.
  `pricing.value` and the alternate framework expect unconditional market win
  probabilities: multiply conditional market probability by the modeled non-push
  mass before comparing an integer threshold.
- Consensus uses complete current same-book instances, latest quotes per side,
  median no-vig probabilities, and normalization over the outcome set. With at
  least three books, probabilities outside max(10 percentage points, 4 median
  absolute deviations) are excluded. Two fresh agreeing books are required for
  an executable card. These are research defaults, not fitted sharp-book weights.
- The inherited scanner uncertainty is a relative haircut `p*(1-u)`. New distribution
  research explicitly uses an absolute probability-point haircut `max(0,p-u)`.
  Do not interchange these parameters. Neither is a fitted uncertainty estimate
  merely because the function accepts it.
- Independent joint probabilities require explicit independence confirmation.
  Correlated parlays use aligned shared model scenarios. Pairwise correlation
  alone cannot determine a multi-leg joint probability. These tools cannot
  self-approve a wager; fitted dependence and actual payout data are still needed.
- Profit boosts increase net winnings, not returned stake. `profit_cap` caps
  additional promotional profit. Bonus-bet cash value assumes the bonus stake
  is not returned. Eligibility, expiry, and maximum stakes still require verified
  offer terms before production use.
- Units have one application setting, default $30. Risk tiers are .25/.50/.75/1u;
  fractional Kelly and portfolio limits can reduce the tier or pass. There is no
  loss-recovery escalation. Drawdown is an explicit input; automatic bankroll
  reconciliation is pending.
- Price CLV is entry decimal / comparable closing decimal minus one. Probability
  CLV is closing probability minus entry probability. Compare the same selection,
  line, period, and settlement rules. Spread-point movement requires a separate
  model; do not substitute spread points into a price-CLV formula.
- Closing research returns `CLOSING_PROXY` only with a qualifying multi-book snapshot
  in the final two minutes before start. It never labels an old quote the official
  close. Automatic historical close ingestion is pending.
- Backtests require decision, feature-availability, model-fit, odds-source,
  odds-receipt, start, and settlement timestamps. They retain all supplied rows
  and rejection reasons, costs, slippage, available limits, overlapping cash use,
  probability scores, and settled-equity drawdown. Walk-forward model training
  and independent out-of-sample data remain caller duties.

# Today research hub

The existing `/v1/vip/rankings` endpoint requires the existing member session.
All entries are scoped to upcoming games on the current America/Chicago date.
Fresh ranking prices have a five-minute ceiling. No new paid dependencies or
provider requests run on page load.

## Ranking semantics

- Likelihood lists expose the probability source on every entry. A shadow model
  remains research, and no-vig market evidence is not an independent forecast.
- Value lists require a production-approved model and positive expected value at
  the exact observed price. These lists do not issue official wagers.
- Receiving overs retain exact lines. Statistical yardage means are unavailable
  unless a future provider/model explicitly supplies that output.
- NFL anytime touchdowns are separate from passing touchdowns and first TD.
- Other player markets are separated into market-specific lists.
- Fewer than ten supported candidates is a valid complete result.

## Reviewed research fallback

The existing authenticated source-pick ingestion API and append-only `source_pick`
records provide the input. Only independently reviewed records with HTTPS source
links, matching event identity, recent publication/retrieval timestamps and no
conflicting selections appear as WEB-RESEARCH LEAN. Claimed source probabilities
are never promoted into model probabilities. Matchup pages may use this fallback
when no model/market winner is available.

This is NOT an automated web-search integration. The existing source registry is
metadata, not a fetcher. A configured authorized search/content provider and an
evidence extraction/review workflow are still required for autonomous collection.
No provider coverage or predictive validation is assumed.

## Simulations and graphics

Margin/total histograms aggregate the exact existing paired-score samples or
weighted NHL score grid. Probabilities sum to one. User-entered spread/total
lines evaluate the baseline distribution; they do not change team strength.
Missing artifacts and quarantined models remain blocked. All simulation outputs
remain shadow research. `/v1/vip/slate.png` exports one complete eligible daily
slate with the approved logo; it shares the Discord renderer.

## Verification boundaries

The worker's version-8 acceptance check verifies authenticated transport, date
scope and logout using the verified owner account. It does not constitute an
ordinary-member walkthrough or model validation. Full predictive evaluation,
actual Discord attachments, production restore testing, and automated source
collection require separate verification.

# NBA/NHL joint evidence integration

This change builds on the unmerged paid-player integration in PR #90. It is
research-only and does not complete or replace the full boost engine in PR #80.
It changes no deployment, scheduler, database schema, permissions or model artifact.

The private capture and audit commands from PR #80 are now available alongside
the paid-player pipeline. Forecasts bind to exact ordered legs and immutable
model/source receipts. Settlements require authoritative final results; voids,
DNPs and pushes are excluded from binary scoring. Capture requires the explicit
`--commit-evidence` flag. No automatic capture job is enabled.

Read-only operator checks in an authorized runtime:

```
python -m tools.boost_joint_capture inventory
python -m tools.boost_joint_capture audit
python -m tools.audit_boost_joint_evidence --input /private/frozen-joint.jsonl
```

The strict audit rejects forecasts made before model training was complete.
Test/prospective partitions must be event-disjoint and share frozen training
boundaries. Equal game weights prevent a game with many tickets from dominating.
Fixed probability bins expose calibration errors that cancel in a global mean.
The JSONL command succeeds only when both sports have sufficient test and
prospective evidence and beat their independent combined-ticket market baseline
on both Brier and log loss. This is eligibility for review, never release approval.
The legacy `all_requested_sports_verified` field means sport presence only;
use `research_review_eligible` for review eligibility. `release_ready` stays false.

The NHL injury parser supports the observed team-filtered flat ESPN response
and the older grouped response. Explicit matching team coverage is required;
unknown status on a listed player is unavailable. The NHL paid-player screen
uses saved exact-line research probabilities and explains missing evidence.

## Outstanding release evidence

- Review and live inference integration of the fitted NBA/NHL historical research
  artifacts. The historical workflow succeeded, but the benchmark artifacts are
  not approved live joint models; NFL dependence must not be relabeled.
- At least 200 independent games per model/version in each test and prospective
  partition, genuine exact-ticket market receipts, source review, calibration
  uncertainty and stability review. Unit fixtures never count toward these totals.
- Fresh verified NHL availability and goalie starters, reviewed paid identities,
  complete NBA/NFL/NHL endpoint coverage and saved forecasts on the real slate.
- Final hosted Python, browser and container checks; integrated boost/VIP/Discord
  acceptance; reconciliation of PR #80 with current production.

No merge or deployment is justified by this change alone. Missing pregame
forecasts and bookmaker receipts cannot be recreated after the outcomes are known.

## Historical model-building experiment

`tools/train_nba_nhl_joint.py` uses the existing public-history collectors and
causal dataset builders. It retains the existing pre-July-2024 count marginals,
fits same-player residual rank dependence on July 2024–June 2025, and evaluates
July 2025–June 2026. At least 200 distinct games in both periods are required
per pair. Labels crossing a split boundary are excluded. Future features,
duplicate identities, cross-market event mismatches and overlapping marginal
training are rejected. Holdout labels do not affect fitted ranks or model identity.

Predeclared pairs are NBA points/rebounds, points/assists and rebounds/assists;
NHL goals/shots, goals/assists and assists/shots. Each is evaluated at fixed
research thresholds against independence using game-weighted Brier/log loss.
The resulting dependence experiment is not a full coherent player simulator,
does not support cross-player tickets, and does not model participation/voids.
These benchmark results do not prove calibration at arbitrary sportsbook lines.

The isolated `NBA NHL historical joint research` workflow captures source data
and uploads separate experiment artifacts. It has read-only repository access,
uses no production secrets, writes no live model files, and does not deploy.
Outputs remain SHADOW_ONLY with zero prospective samples regardless of scores.
An absent/failed bucket is reported, never replaced by independent-leg betting EV.

Reports include paired game-bootstrap 95% intervals (1,000 resamples, fixed seed)
for score improvements, and fixed-decile event-weighted calibration summaries.
Game clustering handles tickets from the same game, but not recurring-player
serial dependence. NHL captures must match the provider's declared total, and
capture receipts are retained with each experiment. No holdout-driven threshold
search or automatic model selection is performed.

## DraftKings combined-offer custody

The private `freeze` input now optionally accepts `offered_quote`, using the same
`provider`, `observed_at`, `payload` envelope as other source receipts. Its payload
requires `quote_kind: sportsbook_combined_ticket`,
`price_basis: direct_sportsbook_quote`, `book`, `quote_id`, `receipt_reference`,
`decimal_odds`, and the exact `event_id`, `ticket_id`, `leg_ids` and canonical `legs`.
Retain the original receipt privately. An entered label or hash does not prove
authenticity; the operator must verify it against the sportsbook receipt.

A one-sided DraftKings SGP quote is retained immutably through settlement but does
not create a no-vig market baseline or enter the paired-market acceptance audit.
Individual prop prices, multiplied leg prices, stale receipts and changed legs
cannot stand in for a combined offer. No bookmaker account action is automated.

## Discord status destination preflight

`python -m tools.check_discord_status_target --status-channel CHANNEL_ID` performs
GET requests and a read-only database query. It checks the configured server
owner, bot membership and existing private-channel grants, including stored paid
roles. It never posts, changes permissions, changes environment variables or
deploys. A validated replacement still requires the corresponding reviewed
service configuration change and live delivery verification after release.

## Explicit prospective benchmark collection

Frozen models from historical run 42771517832 are retained under
`research_artifacts/joint`, outside live model paths. The manifest locks source
workflow, compressed/raw/canonical checksums, versions and artifact creation time.
The collection command verifies the exact marginal artifacts, rank support and
independent-game sample counts before inference. It never refits on new outcomes.

`python -m tools.capture_joint_research --sport NHL --event OFFICIAL_GAME_ID
--player OFFICIAL_PLAYER_ID --pair 0 --execute` validates an upcoming official
game and exact roster identity, fetches fresh inputs and freezes one same-player
joint forecast. NBA uses ESPN event/player IDs. Pair indices 0–2 refer to the
predeclared benchmark pairs in the historical protocol; all sides remain over at
the original benchmark thresholds. Omit `--execute` for read-only input checks.
This command is operator-invoked, has no scheduler, does not fetch paid odds and
does not publish. It does not mean full-slate coverage. Unverified inputs block
capture; successful reruns preserve the original forecast.

The original DraftKings combined offer is separate evidence. Forecasts without
such receipts remain marked missing market baseline. Historical research models
have no participation/void model; DNPs and voids must be explicitly excluded at
settlement. No single successful capture establishes calibration or readiness.
# Prospective collection and result polling

Live matchup audit on 2026-11-11 UTC: all 50 official roster players for the
next Tampa Bay–Buffalo game were checked across 185 applicable contexts (four
skater markets, saves for goalies). 160 contexts passed all feature gates across
40 skaters. Remaining contexts were blocked by injuries, insufficient history,
or unconfirmed starting goalies. This covers one matchup, not the full slate.
39 additional official-ID goals/shots forecasts were frozen; the original one
was preserved. The private archive now contains 40 NHL and one NBA forecast,
spanning only two independent events, with no final results or combined quotes.

Paid NHL requests returned six upcoming games, 50 players for the scoped two
teams, and 941 prop rows for the matchup. All 50 scoped paid birth dates were
one day earlier than the corresponding official roster dates. Original source
records and coverage diagnostics are retained in the private review archive.
Identity candidates now reject explicit birth-date conflicts; no silent date
normalization, independent-review attestation, or paid-model promotion occurs.

An actual later pregame combined offer can be retained with
`python -m tools.boost_joint_capture quote --input PRIVATE_RECEIPT.json --commit-evidence`.
The private JSON contains `forecast_id` and the existing `offered_quote` envelope.
It must identify the exact frozen event, ticket and legs, sportsbook, direct
combined decimal odds, quote ID, observation time and original receipt reference.
The quote is appended separately; forecast times/probabilities never change.
It does not create a two-sided no-vig baseline or make the row audit-eligible.

The first real NHL goals/shots forecast was frozen on 2026-11-11 UTC for
official game `nhl:2026020293`, player `8478519`, before its scheduled start.
Its private receipt is `a27884c1397124fb1e1fabeb712b96024e86a0dc6d5896e0d6cb8cf2190e5de4`.
No sportsbook quote or result is asserted for this forecast.

Run `python -m tools.settle_joint_research --forecast FORECAST_ID` to read an
official boxscore and verify exact event/player/stat identities. `--execute`
appends a final result only after the official source reports completion.
Unfinished games remain pending; missing statistics and ambiguous participation
remain blocked. Source observations retain the raw response and its checksum.
The time a final status was observed is explicitly distinguished from the exact
game completion time, which these public feeds generally do not provide.

NBA season CSVs are now spooled to temporary files in bounded chunks to avoid
holding raw bytes plus decoded copies of entire season releases in memory.
No recurring job, deployment, sportsbook account action, or model promotion is
enabled by these operator-invoked tools.


## Bounded result collection

`python -m tools.settle_joint_batch` checks up to 100 unresolved forecasts in
read-only mode. Add `--execute` only for authorized append-only result collection.
Resolved forecasts are excluded; future games remain pending without a request.
Each official boxscore is reused within that invocation, but player IDs, markets,
participation and event chronology are checked separately for every forecast.
One failed player does not prevent independent records from being checked.

A batch allows 1–200 forecasts and a 1–120 second processing budget (default 60).
The budget is checked between forecasts; an in-flight source request can finish
later under its HTTP timeout. When `has_more` is true, pass `next_cursor` as
`--after` for the next batch. After completing a sweep, start the next polling
sweep without a cursor so pending games are revisited. No background job is
installed or enabled by this command. Output reports blocked records without
printing upstream exception messages or private source payloads.

The latest live archive contains 41 pregame forecasts across two events and no
final results. One genuine public DraftKings prebuilt combined quote was saved
separately, but its two-player goals legs do not match the same-player forecasts.
It is not matching calibration evidence. The earlier no-quote observation in
this document predates that capture. Full-slate coverage and the 50 conflicting
paid/official NHL birth dates remain unresolved.

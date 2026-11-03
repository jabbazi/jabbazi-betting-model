# All-model research routing follow-up

Base: deployed PR86 (`7dc640132563c6717c3926b21972bc85bba36685`). This is a
routing/serialization/identity repair, not a model retraining or paid-feed release.

## Corrected breaks

1. NHL accepted a unique canonical home/away/start schedule match but subsequently
   marked event identity false unless the official schedule also supplied the
   sportsbook event ID. The same verified cross-provider identity rule already
   used for NFL/CFB/NBA/MLB is now applied after the NHL uniqueness, season, schedule,
   freshness and explicit-conflicting-ID checks. Empty odds IDs, conflicting IDs,
   duplicate matches, wrong season, moved starts, completed and unscheduled games
   remain rejected. No cash approval flag is changed.
2. Player models emitted a fitted distribution without its version; reliability
   serialization discarded it altogether. Actual fitted mean, model version,
   inference timestamp, feature timestamp, exact quote market/side/line, and base
   model market now survive action -> immutable research sheet -> VIP/Discord.
   Alternate quote lines stay distinct. Binary event probabilities are not labeled
   projected statistical totals. No bookmaker threshold is used as a mean.
3. MLB batter/pitcher markets were absent from the player-probability summary's
   league/prefix allowlist. All four currently modeled player leagues now use that
   endpoint. The college player policy remains unchanged.
4. Safe exact rejection reasons survive archiving and are explained consistently
   on VIP and private Discord replies. Raw vendor errors and private inputs are
   not exposed. Unverified data is not made visible merely to fill a page.
5. A new authenticated Model connections page reports loaded artifacts, saved
   selections, usable forecasts and unavailable reasons separately for NFL, CFB,
   NBA, NHL and MLB. It uses saved records only. The owner status connector exposes
   the same counts/reasons without player payloads so production can be audited.

## Current model scope, not live coverage

The existing bundled registry has 37 fitted player artifacts: NBA 12, NFL 9,
NHL 5, MLB 11. NHL blocked-shots and power-play-point categories are registered
but have no bundled fitted artifacts. They must be displayed as unavailable.
NFL anytime-TD and MLB HR legacy calibrators lack verified negative-side mapping;
under/no forecasts from those two are still withheld. This release does not
rewrite their calibration or pretend those sides are supported.

## Tests and limits

The routing matrix exercises actual bundled player-model inference with synthetic
point-in-time features and quotes, through action reliability, immutable saving,
authenticated VIP board/detail/probability endpoints and the private Discord
formatter. It covers positive selections and alternate under selections, with
explicit unavailable assertions for the two legacy negative-side cases. Additional
cases cover five team-model board/Discord paths, actual NHL inference, rejected
identity mismatches, no external calls, preserved college policy, status summaries,
private error redaction and unknown-vs-missing registry states.

Tests do not establish live paid subscriptions, complete slate collection,
calibration, profitability, current member delivery or full boost acceptance.
The delayed V7 paid-ingestion branches are not merged by this follow-up. Missing
live forecasts are still missing. A bounded live verification scan and the saved
routing counts must be reported separately from fixture tests.

## Release boundary

The original display-release boundary is retained for scanner, providers,
artifacts, cash rules, auth, persistence, schedules, configuration and build files.
A documented per-file before/after hash allowlist permits only the reviewed NHL
identity/metadata changes and the read-only owner diagnostic additions. Every
other previously frozen source remains byte-for-byte unchanged. No data migration,
role changes, model promotion, subscription purchase or increased quota is added.

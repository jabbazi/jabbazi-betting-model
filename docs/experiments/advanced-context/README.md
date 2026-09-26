# NFL/MLB advanced inputs — September 23, 2026

Implemented and tested an **offline feature-preparation pipeline**. No advanced
model has been trained, no predictive improvement is claimed, and no cloud model
or scanner probability has changed. The existing models remain SHADOW_ONLY.

Later source-capture update: [NFL real-data results](../nfl-context-capture/README.md)
and [MLB staging results](../mlb-history-capture/README.md) now document successful
bounded public-data imports. The earlier inventory below remains an audit of the
five original local files, not an inventory of the new Actions artifacts.

## What works

`jabazi.features.advanced.AdvancedContext` consumes provider-neutral archived
observations and creates a reproducible feature vector for a specified pregame
decision time. It requires real-data provenance, a canonical ID namespace, raw
source hashes, archive references and timezone-aware observation times.

- NFL: play-weighted offensive EPA and success rate, defensive EPA allowed and
  success rate allowed. The import adapter accepts a complete final game of
  nflverse-style plays, excludes no-play/special-team/spike/kneel events, retains
  passing sacks, and defines success as EPA > 0. These are unadjusted team rates;
  there is no opponent adjustment, QB injury model or usage projection yet.
- MLB: prior-start strikeout and walk rates per batter faced, ERA, outs/pitches
  per start and rest. Baseball `5.2` innings becomes **17 outs**. Historical
  actual starters do not identify the pitcher for the target game: a recent,
  archived, confirmed announcement for the exact event and start time is required.
- Later corrections cannot rewrite an earlier feature vector. A latest-known
  scratch, unknown starter, reschedule or void takes precedence over older data.
  Event IDs distinguish doubleheaders. Missing coverage returns INSUFFICIENT_DATA
  with no feature vector or probability, rather than filling with fabricated data.
- Every output records the policy, source checksum, used snapshot IDs/hashes and
  a feature version. The manifest describes the ingestion process's evidence;
  it is not independent proof that a timestamp or license is authentic.

Defaults are 8 prior games/starts, at least 4, within 370 days, with starter
observations no older than 6 hours. These are configurable research policies,
not optimized settings or validation thresholds. No train/validation result has
been used to choose them. Confirming a starter still does not verify the lineup,
bullpen, injury, weather, umpire or all other necessary model inputs.

## Actual local data audit

`input-audit.json` is a reproducible inventory of five explicitly listed files:

| Input | Observed coverage | Missing evidence |
|---|---|---|
| NFL normalized history | 1,455 games | Advanced snapshots and odds observation times: 0 |
| MLB normalized history | 14,673 games | Advanced snapshots and odds observation times: 0 |
| MLB raw 2024 schedule | 2,512 records | Probable-pitcher entries and box scores: 0 |
| MLB raw 2025 schedule | 2,511 records | Probable-pitcher entries and box scores: 0 |
| NFL raw schedule | 7,548 rows; QB/weather fields exist | No observation timestamps or play-by-play |

Final QB names/weather in the schedule were deliberately not inserted as
historical pregame features. A file downloaded today cannot claim it was captured
before a game played last year. The counts include schedule records that may not
be eligible completed games, and are not training-sample counts. This audit did
not inspect cloud secrets, provider accounts or entitlements.

## Input contract and command

The input document contains `manifest` and `snapshots`. The manifest requires:

```json
{
  "schema": "advanced-context-0.2.0",
  "data_mode": "real",
  "provider": "provider name",
  "id_namespace": "documented canonical ID mapping",
  "research_rights_reference": "reference to reviewed permission evidence"
}
```

Every snapshot requires `snapshot_id`, `event_id`, `entity_id`, `kind`, `status`,
`starts_at`, `observed_at`, a 64-character `raw_sha256`, and `archive_reference`.
An optional `published_at` may delay availability but can never move it earlier
than the observed time. Keep the original captured raw file at the archive
reference. Append corrections as new snapshots; do not change original captures.

Completed-stat snapshots also require exactly one of actual `ended_at` or a
conservative `completed_by` bound, and numeric `values` matching
`NFL_FIELDS` or `MLB_FIELDS` in the module. A `mlb_starter` uses `entity_id` for
the team and `pitcher_id` for the announced player, with a status of `confirmed`,
`probable`, `scratched` or `unknown`. Scratched/unknown entries have null pitcher
IDs. Only confirmed entries can currently admit a starter feature vector.

Requests are a JSON array with `sport`, `event_id`, `home_id`, `away_id`,
`prediction_at` and `starts_at`. Join IDs through a verified provider crosswalk;
the importer intentionally does not fuzzy-match names. Legacy `0.1.0` manifests
remain supported. A final score observed today can supply a conservative
completion bound today, but cannot establish original historical availability.
Executable **synthetic**
schema examples are in `tests/test_advanced_features.py`.

```bash
python -m jabazi.features.advanced --snapshots /path/to/archived-snapshots.json \
  --requests /path/to/prediction-times.json --output /path/to/feature-results.json
```

The command performs no network calls and produces no betting probabilities.
The adapters in `providers/advanced_stats.py` normalize already-captured inputs;
they do not fetch or certify provider coverage. They require a complete final
game attestation from the ingestion layer, which still needs real-feed testing.

## Verification

- 24 new tests passed: future/revised/published-after-decision exclusion;
  same-game exclusion; duplicate revisions; voids; source integrity/schema;
  caller mutation; scratched/replaced/probable/stale starters; rescheduling;
  doubleheaders; innings math; NFL play filters/signs; missing EPA; and CLI output.
- Full local suite: **291 passed**, one existing discord.py audioop deprecation
  warning. Ruff and whitespace checks passed. Synthetic tests verify code behavior,
  not model calibration, real feed quality, profitability, or cloud operation.
- GitHub CI for code commit `aed2d8945258d770fb18fe4e28aac3d950efc743`
  passed in runs `35922519903` and `35922514549`. The PostgreSQL-enabled suite
  reported **305 passed**. API/container startup, database backup/restore, and
  database-outage smoke checks also passed. These are CI checks, not a production
  deployment or an advanced-model performance test.

## Data access and next experiment

1. Obtain/verify archived NFL play-by-play and MLB pitching appearances plus
   original pregame starter announcements. Preserve observed-at history and
   correction versions. Public current files can help begin future collection;
   their current timestamps cannot reconstruct past ingestion. The NFL data
   schedule documents postgame updates and subsequent stat corrections.
2. Confirm provider terms for commercial modeling and member-facing derived
   output. SportsDataIO is one possible combined MLB/NFL source; request real
   historical stats, starters/injuries/lineups and timestamped archives. Its
   commercial pricing is quote-based. Free trial data is scrambled, and Discovery
   Lab is personal/noncommercial; neither establishes the needed production rights.
   No quote was requested, contract accepted or data purchased in this work.
3. Confirm the existing odds account's historical entitlement and obtain offered-at
   and closing-at prices with matching market/line/settlement IDs. Live odds access
   does not demonstrate historical access. Keys belong in secret settings only.
4. Join the new vectors to the existing moneyline research experiment with coverage
   reports, fixed feature ablations and paired comparisons on identical games.
   Freeze the protocol before looking at additional results. 2025 is already a
   viewed development period; new features need a genuinely unseen forward sample.
5. Add QB/injury context, lineups and bullpen inputs only through similarly audited
   captures. Player props and anytime TD require separate usage/distribution
   targets and remain untrained. Do not turn these rates directly into win or prop
   probabilities, and do not remove the live approval gate.

No additional user login was verified as necessary by this local audit. Any
provider access request must specify the feed, history, allowed modeling/display
use and cost first. The next dependency is actual suitable data, not a claim that
these offline importers already run in the cloud.

Primary references checked September 23, 2026:

- [nflverse data schedules and revisions](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html)
- [nflverse play-by-play loader](https://nflreadr.nflverse.com/reference/load_pbp.html)
- [SportsDataIO testing modes](https://sportsdata.io/developers/apis)
- [SportsDataIO modeling/display rights and commercial pricing](https://sportsdata.io/help/data-rights-and-licensing-questions)

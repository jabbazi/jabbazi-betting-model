# Saved research repair: VIP + Discord

Scope: continue the existing application on `feature/vip-discord-research-repair`,
from source commit `0e7ed5d1aa853e344a9564bb884987aaf2fb42c5`. No new app,
provider subscriptions, production configuration, credentials or model promotion.
The repair is development work; a green software test is not live model acceptance.

## Root causes and implementation

* The main VIP board read only `research_sheet`. Paid fitted records were added
  exclusively to a separate Top 10 endpoint. The shared saved board now combines
  existing research sheets and latest explicit per-sport `paid_player_scan` buckets.
  No raw provider endpoint is fetched by these read paths.
* VALIDATING/LIMITED_LIVE models were excluded from game winner selection.
  Valid versioned research is now visible with its stage, without official-pick
  approval. Invalidated, quarantined, unhealthy and mismatched records stay blocked.
* Price freshness also controlled forecast visibility. The canonical projection
  now tracks model/feature freshness separately, retains still-valid research,
  and clears current price/EV/edge/play-to when the quote is unusable. Integer
  O/U lines do not acquire invented binary push handling.
* Main props navigation exposed too few categories, did not reach all saved paid
  rows, and could lose filters. The full board has observed/category counts,
  filters for game/player/team/market/side/book/stage, deterministic pagination,
  working drilldowns and explicit missing-category/no-match/service-error states.
* General rankings excluded unders. Model-only per-market likelihood, genuine
  fitted means and approved fresh-price value views are now separate. Discord
  Top 10 shares the ranking function rather than multiplying or inventing values.
* LAB GET previously queried a paid reader. It now reads allowlisted saved
  `paid_lab_signal_snapshot` data, with explicit stale/missing/unsupported state.
* `/props` only issued a link. Private `/props`, `/moneylines` and `/top10` now
  produce saved canonical summaries and scoped private app links after fresh
  membership/rules checks. Replies suppress all mentions. More rows are accessible
  by command page or full app; no public research feed is activated.
* Official-pick polling checked a channel even when no eligible pick existed.
  Channel validation now occurs only after candidate eligibility, preserving
  permission and durable delivery checks. This does not fix an actual missing
  or inaccessible status channel.

## User-facing organization

The existing HOME / TOP 10 / +EV / SCANNER / SHEETS / MORE navigation, approved
logo and black/pink styles are retained. A persistent sport/date selector and
Moneylines / Player Props / Top 10 / All Markets shortcuts are shared across
screens. Full filters are expandable; records are not buried beneath a long form.
Saved schedules retain games with missing model forecasts. Market leans are
explicitly distinct from model winners. Detail links reach all player and game
markets; Top 10 is never represented as the complete database.

Rows may still be unavailable because there are no saved forecasts, no reviewed
identity mapping, no authentic pregame features, an expired model snapshot or an
unsupported market. This display repair does not manufacture those inputs.
Read bounds remain explicit; a large or malformed saved source reports partial
coverage. Per-sport saved snapshots can have different timestamps, shown as such.

## Tests and evidence

`tests/test_vip_research_repair.py` exercises saved paid rows beyond page 1,
canonical API/Discord agreement, alternate lines, unders, missing markets,
validation stages, quarantines, malformed rows, schedule changes, stale quotes,
unsupported push settlement, no paid calls on view, auth and Discord no-ping gates.

`tests/vip_repair_browser.py` loads the application's actual HTML/CSS/JS into
Chromium and bridges fetch to the real authenticated FastAPI TestClient. Inputs
and role checks are **synthetic fixtures**, not real subscriptions or Discord
membership. It covers pagination, moneylines, player drilldown, projections,
filter recovery, date/sport changes, service retry, stale-response isolation,
mobile overflow and offline clearing. No browser security policy is changed.

The normal CI HTTPS/browser scenarios remain separate. Local before screenshots
use unchanged baseline assets and the same synthetic saved-data fixture. These
are not production screenshots or live paid-provider acceptance.

## Integration/release boundaries

PR83 already owns comprehensive paid ingestion. PR84's overlapping LAB audit
must not be stacked into the scanner again; that would duplicate paid collection.
This repair uses PR83's saved records, not PR84's extra provider calls.

The branch inherits the unmerged V7 ingestion work. **Do not deploy the entire
branch as a supposedly display-only hotfix.** Review the combined dependencies,
preserve the production scanner hotfix, verify final CI and rollback, and perform
scoped authenticated staging/live acceptance before merging a production release.
Full model retraining/prospective calibration is not a prerequisite to honest
research display; betting approval and optimized four-leg joint EV remain separate.

No scheduler was altered and no new recurring job was created. Existing schedule
intent, timezone rules and durable delivery guards are preserved, not newly
certified. No live Discord send, actual channel repair or production deployment
is claimed by this development increment.

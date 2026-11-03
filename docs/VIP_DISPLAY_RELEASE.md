# VIP and Discord saved-research display release

## Scope
Based directly on production `c5caee3dfd0ecb4523b54b943a54d6f89de0b2f5`, not on the
unreleased V7 ingestion branch. This extracts the tested presentation work from
PR85 without merging PR80/83/84, activating a collector, changing credentials,
model files, cash approval, scanner limits, schedules, auth, or database schema.
No migration is introduced. Existing persisted data and IDs are preserved.

## Root causes and fixes
- Props used a bounded ordinary board while saved fitted paid rows lived in a
  different record type. The canonical member board now reads both, per sport
  and date, with exact model provenance. Missing paid records do not erase teams.
- Some filters conflated executable price freshness with research visibility.
  Safe current forecasts survive stale prices, while current EV/play-to disappear.
- Props, alternates and unders were buried; all permitted rows now have working
  paging, facets, player/game links and available-market counts, not only Top10.
- Moneyline winners now use actual versioned model estimates. Observed schedule
  games without forecasts stay visible. Market leans are explicitly separate.
- Global alias search no longer inherits an invisible NBA-only filter.
- Dated Discord links preserve their Chicago slate. Expired dates are rejected
  explicitly; manual date switching removes sticky overrides.
- Different sportsbooks' paid quotes retain separate identities and prices,
  without creating duplicate Top10 entries for one player/stat.
- VIP model readiness previously reused an owner diagnostic that could probe
  providers. A saved-only registry reader now serves member readiness.
- Private Discord /props, /moneylines and /top10 use the same saved board,
  fresh member-role verification, ephemeral responses, no mentions, date links
  and pagination hints. No public publication or wager is triggered.
- A channel lookup is deferred when there is no eligible official pick. This
  does not claim to repair the existing status-channel HTTP404.

## Evidence and boundaries
Development tests use synthetic roles, prices and forecasts, conspicuously
labeled on screenshots. Real HTTPS ticket/session and browser regression flows
run in hosted CI. Before/after images compare actual production and repaired
assets against the same fixture; neither image is a live member session.

The UI does not create missing paid probabilities, validate a model, authorize
SGP EV, or backfill prospective outcomes. Existing collection/model work is
still deferred. Only observed schedules and persisted research can be shown.

## Release checks
The production dependency boundary is checked by tests: scanner, provider/model
code and artifacts, auth/member gates, persistence, runtime, configuration and
schedules retain production hashes. The new LAB member reader has no HTTP client.

Before deployment: verify final exact-head Python, HTTPS browser and container
CI; compare the production base again; retain old API/Worker SHAs and inspect
service health. Deploy only this reviewed scoped release, not stacked feature
branches. After deployment verify both service revisions, health, anonymous
access denial, existing login, saved moneyline/props display and command sync.
A real member session and actual Discord delivery receipt must be reported
separately from fixture tests; missing receipts cannot be called live acceptance.

Rollback is the previous service revision or a reviewed revert of this scoped
commit. No destructive data or schema rollback is needed. Preserve auto-deploy
settings, roles, channel IDs and provider billing. Do not delete any research.

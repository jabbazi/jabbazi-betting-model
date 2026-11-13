# NFL / NBA MySportsFeeds preparation

Scope: NFL and NBA only. Intended package is CORE + STATS + DETAILS, Non-Live.
No subscription has been purchased or activated by this change. Do not assume
the pending quote, discount, licensing, history or trial terms are finalized.

## Prepared now

- Disabled-by-default, fixed-host v2.1 transport with header-only authentication.
- Explicit daily games/game-log and numeric game boxscore/lineup/play-by-play routes.
- Six HTTP attempts maximum per client batch, at most one transient retry,
  ten-second HTTP timeouts, response deadline and four-MiB response limit.
- Five-minute in-memory cache scoped by league, season, feed and date/game.
  Expired responses are not silently served as fresh data. Cache is not durable.
- Authentication, entitlement, rate-limit, empty-response and network diagnostics
  use controlled codes; no key or upstream error body is printed.
- Receipt timestamp, checksum and source URL; every response remains UNVERIFIED.
- Offline readiness in the existing runtime doctor and a standalone probe command.

This is a staging transport, not automatic feature ingestion, an approved model,
or a new odds feed. Existing scanner providers and member output are unchanged.
An HTTP 200, an empty JSON object, or a configured key is not a coverage pass.
The readiness command reports configuration, not historical probe results.

## Credential handoff and first test

Store the key only in the existing deployment's secret environment variable
`JABBAZI_MSF_API_KEY`. Never paste it into chat, commit it, put it in a URL,
or expose it to frontend JavaScript. Keep `JABBAZI_MSF_ENABLED=false` initially.
No account password is required by the v2.x authentication scheme in the
provider's published wrapper: API key plus the constant `MYSPORTSFEEDS` password.

Offline readiness, with no provider requests:

```sh
python -m jabazi.providers.mysportsfeeds
```

After trial terms and exact season entitlements are confirmed, enable this
transport explicitly in an isolated evaluation process. Use an entitled season
and a known game date, for example (selectors are illustrative, not verified):

```sh
python -m jabazi.providers.mysportsfeeds --probe --league nfl --season 2026-regular --date 2026-10-14
```

The probe prints metadata only and does not persist data, run a model, send an
alert or alter the official ledger. The provider date selector is a retrieval
hint: it must not replace America/Chicago eligibility checks on normalized event
timestamps. Historical training requests must remain separate from daily output.

## Required before connecting scan everything / the app

1. Verify both leagues, each needed feed, season access, trial restrictions and
   pregame/postgame update times with actual authorized responses.
2. Capture sanitized, licensed representative fixtures and confirm schemas,
   canonical player/event IDs, timezone semantics, stat units, null handling,
   DNPs, canceled/postponed games, corrections and completed-game status.
3. Map NFL rushing/receiving/passing results and workload, plus NBA minutes,
   points/rebounds/assists/threes and workload. Audit snap/route/red-zone coverage;
   do not infer those fields exist merely because DETAILS is subscribed.
4. Keep anytime scorer touchdowns distinct from passing TDs and first TD.
   Do not derive calibrated anytime probability solely from expected TD totals.
5. Separate today's slate from the explicitly labeled next-day preview available
   at 11 p.m. America/Chicago. Keep finished games in recap, not new-pick alerts.
6. Add canonical mapping and normalized snapshots to the existing feature store
   only after schema tests; schedule bounded, deduplicated ingestion with shared
   persisted request limits. Do not call this client on every page load.
7. Reuse and audit the existing exact-line odds adapter. MSF ODDS/DFS/PROJECTIONS
   are not included or requested here; statistics do not supply verified prices.
8. Backtest without leakage, evaluate held-out calibration/Brier/log loss and
   market baselines; preserve SHADOW/UNAVAILABLE until validation supports more.
9. Test daily rankings with fewer than ten eligible candidates. Distinguish
   most-likely outcomes, supported value, research leans and official positions.

No production restart is needed for offline preparation. Deploy the tested
integration when credentials and real payload checks are ready. Disable the
MSF flag to stop its probes; existing providers remain intact.

References (read 2026-10-14):
- https://github.com/MySportsFeeds/mysportsfeeds-python/blob/master/ohmysportsfeedspy/v2_1.py
- https://github.com/MySportsFeeds/mysportsfeeds-python#usage
- https://www.mysportsfeeds.com/feed-pricing/
- Full API docs require provider sign-in; public wrapper routes do not prove
  current subscription-specific field coverage.

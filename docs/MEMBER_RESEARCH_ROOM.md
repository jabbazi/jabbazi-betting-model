# JABBAZI member research room

Implements the requested `!vip` → private JABBAZI app flow on the existing Render API,
without exposing the owner's scanner or copying another service's data.

## Member experience

- Type `!vip` in a channel the JABBAZI bot can see. The bot checks current Discord
  membership and an existing approved viewer role (or the verified owner).
- Open the private DM link within five minutes. It works once and creates a
  15-minute research-only session. Retype `!vip` to renew access.
- Tabs: Cheat sheets, Moneylines, Player props, Anytime TD, Insights, Learn how to.
- Filter by sport, date, market, player/team search and Over/Under; sort by time,
  model probability, no-vig market probability or percentage-point edge.
- The member app shows up to 12 supported positive-edge selections per section,
  at most one per game on game sheets, ranked by conservative price value.
  It does not force every game onto the app or rank by hit probability alone.
- Member JSON and PNG downloads recheck price age against the current time:
  prices expire after 120 seconds or at game start, whichever comes first.
  The browser removes expired rows, clears data on failed refresh/logout, and
  stops displaying data when the member session expires. Saved PNGs remain
  historical snapshots, not self-updating prices.
- Discord's separate image-only archive keeps full feed-slate research coverage.
  Model %, Market % and Edge stay separate. Neither display approves bets.
- The server's own icon supplies app branding. No fabricated logos, model grades,
  player portraits, historical hit rates or percentages are introduced.

## Access boundaries

Only the bot can mint a member link after a fresh REST membership check. The API
has no public invitation endpoint. Link/session secrets are random, hashed in
PostgreSQL, and never reused as owner or scanner credentials. The URL fragment
is cleared immediately after page load. Sessions use a Secure, HttpOnly,
SameSite=Strict cookie. Mutating session requests require the configured origin.
Links have atomic single-use claims; logout revokes the session durably.

Role removals prevent new links immediately on the next membership check; an
already-issued session can remain valid for at most 15 minutes. Member routes
return only public research fields and lessons. Refresh reads the saved snapshot;
it does not run a scanner or spend provider credits. Owner, ledger and MCP routes
retain independent authentication. Member tokens cannot authorize those routes.

`JABBAZI_MEMBER_ORIGIN` defaults to `https://jabbazi-research-api.onrender.com`.
Set it to a canonical HTTPS origin if the API moves. `JABBAZI_DISCORD_VIEWER_ROLE_IDS`
continues to define approved roles; no automatic role purchase or privilege grant.

## Event-market ingestion and honest availability

`FeedPlan` first obtains NFL, MLB and CFB game prices, then requests bounded NFL/MLB
player/event markets, then uses remaining budget for secondary sports. It rotates
both events and market bundles using durable request history. Louisiana-facing
college player props remain excluded; permitted team totals remain supported.

Defaults: event odds enabled, three markets per event, at most four event requests,
and a 15-credit worker scan cap. With three primary feeds, normally only two event
requests fit. **This is partial prop coverage, not an all-player/all-game feed.**
Existing monthly reservation limits and provider reserve checks remain enforced.
No subscription upgrade or additional paid infrastructure is created. More frequent
or more comprehensive scans can exhaust the existing allowance sooner; the scanner
stops at its configured monthly limit. `event_market_coverage` is recorded in the
scan audit, sheet snapshot and owner/ChatGPT result, including requested events,
markets, quote counts and partial status.

Configuration: `JABBAZI_EVENT_ODDS_ENABLED`, `JABBAZI_EVENT_MARKETS_PER_EVENT`,
`JABBAZI_EVENT_MAX_EVENTS_PER_RUN`, `JABBAZI_SCAN_MAX_CREDITS`,
`JABBAZI_MONTHLY_CREDIT_LIMIT`. No secret values belong in documentation.

Unmodeled player rows can show a neutral threshold and genuine two-sided no-vig
market reference, but no model percentage or model edge. One-sided anytime-TD odds
cannot provide a no-vig probability and are not passed off as such. NFL/MLB score
models remain SHADOW_ONLY; no validated prop/anytime-TD model is introduced here.
Snapshots are historical prices, not promises of current execution. An independently
reconciled official schedule is still needed to claim complete league coverage.

## External tools and launch status

Insights links to the official Outlier app and Gambly site. This is not an installed
Outlier bot or licensed automated insights feed. No verified public Outlier bot
installation was available from its official documentation. GamblyBot was installed
with owner approval and verified in the server member list. Its installation does
not validate JABBAZI probabilities or place wagers.

The 20 lessons were already published and read back in Discord. Renaming
betting-basics and creating/editing channels needs the owner's Discord session;
the bot's existing permissions do not allow Manage Channel.

Regular ChatGPT authorization is separate from Discord member access. The private
MCP backend/plugin exists, but Developer mode/account authorization and a real
regular-chat tool call remain unverified. See PRIVATE_PLUGIN.md.

## Verification before deployment

Regression tests exercise complete 32-game coverage, stale/missing model handling,
conservative selection across alternate thresholds, atomic member links, expiry,
logout, cross-origin rejection, fresh VIP-role checks, private DM-only links,
member denial at owner/scanner endpoints, and the complete provider → scanner →
archive → prop shortlist path without model fabrication. CI also checks PostgreSQL
and container startup. Live rollout/readback evidence is recorded in
SCANNER_DISCORD_HANDOFF_2026-09-23.md; passing local tests alone is not live proof.

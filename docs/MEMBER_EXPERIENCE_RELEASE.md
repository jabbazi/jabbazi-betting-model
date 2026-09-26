# JABBAZI member experience release — 2026-09-24

## Behavior

The member room opens on **Official card**, with **Results**, the existing research
sheets, insights and Learn How To. Main Card and Sprinkles have separate all-time
records. Empty records stay empty. Pagination includes every issued record;
withdrawals, losses and correction history are retained. No synthetic cards are
shipped or published. Model forecasts remain experimental and never auto-publish.

The owner desk at `/owner/picks` requires the existing owner API credential and
supports preview then publication, WATCH/withdrawal updates, and evidence-backed
results. Keys remain in browser memory, never local storage. Published prices,
selection, units and explanations are immutable. Changing a selection requires a
new card plus withdrawal of the original. A repeated request with the same key is
idempotent; conflicting keys and stale revisions fail. A settlement correction
requires a reason. The desk records decisions; it never places a sportsbook bet.

A card must have an owner-reviewed quote observed in the preceding 120 seconds,
a future event start, a price at or better than its play-to limit, and a positive
stake at most 1u. Sprinkles are capped at 0.25u. This timestamp is an owner assertion,
not a live sportsbook verification by the server. After the quote expires, the
card remains in history with PRICE EXPIRED. It is never labeled BET NOW.

Results are **card returns at published odds and units**, not a claim about any
member's actual bankroll. Pushes retain stake in the ROI denominator; voids do not.
Withdrawn cards remain counted if a result is recorded. A linked owner-reported
ledger position must match the event, market, selection, threshold, participant
and sportsbook. Its settlement/correction is mirrored by the configured worker;
private ledger stake, profit and source evidence are not exposed to members.
Closing-line values use only an exact comparable existing closing proxy; absent
or ambiguous closing evidence remains unavailable. No official bookmaker result
provider has been added, so grading requires recorded evidence.

Discord delivery sends at most five pending card revisions per minute, suppresses
all mentions, validates private targets, and durably claims before sending.
An ambiguous delivery failure is marked `needs_review` rather than duplicated.
Original posts are retained; later revisions go to pick-updates and the full
history is available in the app. If several revisions precede delivery, only the
latest is posted, while all revisions stay in the ledger.

## Access and rollout requirements

Member links remain single-use (five minutes) and sessions last 15 minutes. Every
protected API read now verifies current Discord membership, screening completion,
and the configured paid-access role. Removing the role denies the next request.
The browser checks access every minute and on returning to the page; it clears
rendered private data on failure or expiry. It cannot retract screenshots or data
already seen by an authorized member. Discord outages/rate limits fail closed.
Logout revokes the local session even if Discord is unavailable.

The approved paid-access role is **💎 JABBAZI VIP**, ID `1552470745408340109`.
It must never be included among self-selected notification roles. No memberships,
subscription prices or payment-provider settings are invented or assigned.

Set these nonsecret configuration values on **API and worker**:

```
JABBAZI_DISCORD_GUILD_ID=1552043745153650840
JABBAZI_DISCORD_VIEWER_ROLE_IDS=1552470745408340109
```

Retain the verified owner ID already configured on the worker. Ensure the API also
has that owner ID and the **existing Discord bot token** using Render's secure
configuration. Never put tokens in Git, a report or Discord. Without this token,
protected member reads return 503; do not deploy the API until it is configured.

### Compact cheat-sheet follow-up

Format version 4 replaces the wide image table with a dark, phone-readable JABBAZI
list: sport/date, a selection, and its matchup/start time. Model probability,
market consensus and edge remain in the protected app. Each row is one supported
positive research edge per event/player; multiple thresholds no longer create
repeated layers of the same matchup. Doubleheaders retain separate event IDs and
start times. Discord includes all qualifying rows across automatic pages; the
app keeps its existing top-12-per-group shortlist. A reference-only player market
or a PASS is never styled as a selection. No group is filled merely to have picks.

Rendering rechecks current quote freshness, including previously supplied app
rows. Unhealthy, expired or unmodeled data yields an empty-state image. Images say
RESEARCH ONLY / NOT OFFICIAL PICKS, retain the snapshot timestamp, and never combine
the list into a parlay. Original owner research archives are unchanged. Three
market groups remain available (games/pitchers/batters or games/props/anytime TD).

The deterministic `tools/preview_cheat_sheets.py --output <path.png>` creates a
clearly marked fictional-team sample without provider calls or publication.
Verification: 286 local Python tests passed, including image pagination, exact
market labels, quote expiry, no-model/PASS exclusion and full-name wrapping.
Sample PNG was rendered and visually inspected. The cloud rollout is still
pending; this is not evidence that the new images are deployed.

Additional live Discord work: odds-and-EV-tools now explicitly grants the
existing JABBAZI VIP role View Channel and Read Message History. Its @everyone
visibility denial remains. It was intentionally unsynced from VIP TOOLS so the
owner-archive channel retains its private permissions. The category was not
opened wholesale. Cheat-sheets still requires the coordinated worker viewer-role
configuration described below; granting channel visibility first would make the
current bot reject the unconfigured role and interrupt delivery.

On the worker, retain its current database, bot, owner, scanner and sheet settings;
add the official delivery targets:

```
JABBAZI_DISCORD_MAIN_CARD_CHANNEL_ID=1552382924979052564
JABBAZI_DISCORD_SPRINKLES_CHANNEL_ID=1552383420816953505
JABBAZI_DISCORD_PICK_UPDATES_CHANNEL_ID=1552448288521719878
```

After the worker's viewer-role configuration is updated, grant the VIP role view
and history access to the private cheat-sheets channel while retaining the bot's
posting permissions. Do not grant that role any view access to owner-archive,
model-review or staff channels. Test both a free/alert-only role and the VIP role.

This change reuses the existing append-only `platform_events` schema. No destructive
migration is required. Roll out the API and worker from the same reviewed commit.
Do not merge or deploy the separate research/model-validation branch as part of
this member-experience change.

## Verification and current boundary

Local verification: full suite initially 282 passed, then an additional outage-
logout regression was added and the affected 33 tests passed. Browser logic covers
price/session expiry, failed refresh, concurrent response ordering and access
removal. Ruff F checks and real local HTTP readiness/authentication smoke checks
passed. GitHub CI must additionally verify PostgreSQL/container behavior before
rollout. The cloud browser currently shows Render's sign-in page; this document
is not evidence of deployment.

No model approval changed. NFL/MLB remain subject to their existing validation
gates; player-prop model availability and licensed historical inputs are separate
work. No data was purchased and no real wager/card was manufactured for testing.

## Verified release checkpoint

GitHub Actions run **35939073113** passed on commit
`4c56493f11d897c7c05449e2ab37ceb40aa3b8b1` (PR #4). The remote tree matched the
locally tested tree exactly. CI includes PostgreSQL, container startup,
backup/restore and database-outage checks.

Live Discord changes saved and inspected:
- Created the non-administrative paid-access role above, separate from alert roles.
- Denied public view on VIP PICKS and VIP LOUNGE; granted the VIP role and existing
  JABBAZI Research bot visibility. Member contribution channels remain distinct.
- Main Card and Sprinkles deny member messages and thread creation; the existing
  research bot has explicit send/embed/history permission.
- Pick-updates was unsynced and public. It now denies public view, grants VIP/bot
  access, and retains member-posting restrictions.
- Removed and saved GamblyBot's Administrator permission. It remains installed;
  no new channel access was granted to it. Its betslip workflow was not retested.
- Discord's VIP role preview showed VIP channels and hid model-review,
  owner-archive and other private tools. The preview showed pick-updates as
  read-only. A final free/alert-only preview attempt stalled before verification.

No human VIP membership was manually assigned or removed during this work.
The role-member UI subsequently listed one existing member; payment eligibility
was not inferred or changed. The alert selector was not edited to include VIP.

The browser stopped responding while attempting the final role-preview check.
Render was last observed signed out. No Render credential prompt was submitted,
no API/worker rollout occurred, no fake pick was published and no final screenshot
was captured. The current deployed member portal therefore remains the prior
version. Do not describe the new desk, results sync or live API role checks as
already deployed. Resume by verifying the browser and Render sign-in, then apply
configuration and rollout above; finish free/VIP permission and live portal checks.

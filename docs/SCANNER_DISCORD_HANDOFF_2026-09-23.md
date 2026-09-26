# JABBAZI deployment handoff — September 23, 2026

## Latest verified rollout

The API and worker both run commit `1998e618c37909a7358a052cd8a9a519dc4d9ccd`
from `build/production-foundations`. Render reported both **Live**: API deployment
62 seconds, worker deployment 53.4 seconds. This records work actually performed;
it does not claim continuous overnight coding or production model approval.

### Member app and compact cheat sheets

- [Open JABBAZI GURU](https://jabbazi-research-api.onrender.com/vip).
- Extended the existing Render application with Cheat sheets, Moneylines,
  Player props, Anytime TD, Insights and Learn how to tabs. Search, date, market,
  side and sorting controls use the latest archived scan.
- `!vip` now checks current guild membership and sends a private, single-use DM
  link to approved viewers or the owner. Five-minute link, 15-minute read-only
  session; no scanner, administrative or bankroll access. Full implementation
  and access-boundary details are in [MEMBER_RESEARCH_ROOM.md](MEMBER_RESEARCH_ROOM.md).
- The deployed public login page, loaded JavaScript and the actual Discord server
  icon were visually verified in the browser. Public `/readyz`, `/vip`,
  `/vip/app.js` and `/vip/info` returned 200; unauthenticated member sheets and
  owner review each returned 401.
- **Owner access only at present:** live Discord role inspection found only
  @everyone, GiveawayBot and Ticket Tool. There is no VIP member role, and
  `JABBAZI_DISCORD_VIEWER_ROLE_IDS` is empty. No public access or new role grants
  were silently enabled. The bot process is running, but an actual owner-issued
  `!vip` gateway message, DM click and authenticated browser session have not yet
  been verified. Synthetic automated tests are not claimed as that live flow.
- Format 3 shows a single supported research selection per game, chosen using
  uncertainty-adjusted price value, and compact Model / Market / Edge columns.
  All feed events remain represented even when no selection can be supported.
  Every image page is delivered; no fixed top-two/top-three-team truncation.

### Actual live scan and Discord readback

Healthy snapshot: `2026-09-23T17:03:56.613970+00:00`.

| Sport | Feed games | Games with supported shadow estimate | Player reference rows | Image pages |
| --- | ---: | ---: | --- | --- |
| MLB | 16 | 16 | 1 pitcher + 18 batters | 1 / 1 / 1 |
| NFL | 32 | 17 | 17 player rows; no anytime-TD rows | 2 / 1 / 1 |
| CFB | 71 | 0 | College player props excluded | 3 / 3 / 3 |

These are upcoming games from the provider feed, not a claim that all occur today
or that an independent official schedule was reconciled. Unsupported models and
one-sided scorer markets do not acquire invented percentages.

Read back new Discord attachments after the scan:

- MLB message `1552365042832384133`: game image 1400×1360, pitcher image
  1400×464, batter image 1400×1488.
- NFL message `1552365055989780651`: game images 1400×1872 and 1400×848;
  props 1400×1424; unavailable TD sheet 1400×464.
- CFB message `1552365101497983070`: all nine pages present, max height 1872.
- Publication contains research images; no bets were placed or declared locks.

### NFL/MLB prop ingestion

The worker now spends up to 15 reserved credits per run, preserving primary game
feeds before bounded event/market requests. Existing monthly limit is **3000**.
The first live run reserved 15 credits and requested exactly two events:

- NFL: 1 of 16 eligible events, **194 quotes received**, passing/receiving/rushing yards.
- MLB: 1 of 16 eligible events, **336 quotes received**, strikeouts/hits/total bases.

Events and market bundles rotate using durable history. This is **partial prop
coverage**. Increasing ingestion within the same allowance can reach the monthly
cap sooner; the quota guard stops further paid requests. No data purchase occurred.
No validated player-prop or anytime-TD probability model was created. Player rows
are neutral no-vig market references with model/edge unavailable. Coverage is
included in scan audits, member snapshots and owner/ChatGPT scan responses.

### Validation

- 220 local tests passed; JavaScript syntax and Ruff checks passed.
- GitHub workflow [35892553162](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35892553162)
  succeeded with **234 tests passed** and one upstream deprecation warning.
- CI passed PostgreSQL integration, container build/startup, API authentication
  smoke checks, disposable database backup/restore and outage/readiness checks.
- New tests cover single-use hashed member links, expiry/logout, cross-origin
  rejection, current-role checks, private DM-only delivery, owner/scanner denial,
  32-game coverage and full provider → scanner → archive → prop shortlist wiring.
- A clearly synthetic 16-game image was visually inspected locally. Live Discord
  attachments and the public branded app were subsequently verified separately.

## Still needed from Jabbazi

1. **Discord owner sign-in** in the secure browser flow, or owner changes on the
   phone: create the intended VIP member role, configure approved app access,
   rename betting-basics to learn-how-to, and create the requested Insights
   channel. Existing bot permission lacks Manage Channel; no broader permission
   was granted. All 20 learning messages are already live and verified below.
2. **Gambly decision after sign-in:** its official Discord invitation requests
   Administrator. Installation is pending. Browser's confirmation rule requires
   explicit approval at the time of granting that expanded access; no silent
   Administrator grant was made.
3. **Outlier bot/feed entitlement, if available:** the Insights app tab links to
   the official Outlier app, but no verified public Outlier bot-install link was
   found. An actual automated feed needs Outlier's authorized bot/partner route
   and applicable account/licensing rights. An external link is not a bot install.
4. **Regular ChatGPT connection:** permission to enable Developer mode, then
   native authorization using the private scoped scanner key, and a verified
   model-status/scan call in the intended regular chat. The deployed MCP backend
   and private plugin do not mean account authorization has occurred. The private
   custom GPT connection is a separate existing route. Never paste keys in chat.

NFL/MLB game models remain SHADOW_ONLY. NFL held-out Brier was about 0.2233 versus
market baseline 0.2109; MLB lacked historical-odds comparison. Prop/TD, SGP and CFB
probabilities remain unvalidated or unavailable. Charging for proven model edge
cannot be justified by this infrastructure work alone.

---

## Earlier verification checkpoint (superseded rollout details)

The following evidence predates format 3 and the member portal above. Its original
commit/message references are retained for audit; it is not the current deploy.


Verified September 23, 2026. This records actual work and remaining blockers;
it does not claim unattended overnight coding or production model approval.

## Completed and verified

### Full-slate Discord sheets

- Existing worker deployed commit `410f42aedfe71160e467347c28f90e7d291dfcbb`.
  Render reported Live after a successful 40-second deployment.
- Matchups are grouped by event ID (including distinct doubleheaders), duplicate
  book rows are collapsed, and one representative threshold is shown per market.
  Raw odds-feed events remain represented even when fresh complete prices are
  unavailable. All pages are delivered automatically rather than just page one.
- A rolling-deployment race was found during verification: an old worker claimed
  the sheet before the new renderer started. Format-versioned delivery claims now
  allow the corrected images to be published without relying on the old claim.
- Read-only Discord verification confirmed new 1400-pixel-wide attachments:

| Sport | Feed matchups | Pages by sheet category | Discord message |
| --- | ---: | --- | --- |
| MLB | 16 | 1 / 1 / 1 | `1552353463554416752` |
| NFL | 32 | 2 / 1 / 1 | `1552353495863009302` |
| CFB | 71 | 3 / 3 / 3 | `1552353604306731138` |

These counts include upcoming dates in the current provider feed. They are not a
claim that all games occur today, nor an independent reconciliation against an
official league calendar. Empty prop/TD groups explicitly report unavailable;
no player probabilities were invented. Large slates require additional image pages.
The latest inspected healthy sheet completed at `2026-09-23T16:18:59.216054+00:00`.

### Member learning guide

- Prepared 20 ordered messages covering first-bet steps, personal unit sizing,
  odds/payouts, reading official picks, moneylines, spreads, totals, alternate
  lines, player props, touchdowns, MLB derivatives, periods, parlays/SGPs, round
  robins, teasers, promotions, live bets, cashouts, value/CLV and a final checklist.
- JABBAZI's reference is 1u = $30; members are taught to use their own dollar unit.
  All examples are hypothetical and experimental models are labeled as research.
- Published all 20 messages into existing channel `1552128137238941726` and read
  them back through Discord. All 20 exact expected contents matched, including
  the official-picks channel link; no mass mentions were sent.
- [Open the lesson index](https://discord.com/channels/1552043745153650840/1552128137238941726/1552354576890470511).
  Last message: `1552354640207814706`. Readable copy: [LEARN_HOW_TO.md](discord/LEARN_HOW_TO.md).
- **Rename still pending.** Discord rejected PATCH with HTTP 403. The bot has
  View Channel, Send Messages and Read Message History, but not Manage Channel.
  It was not granted broader permissions. The channel still reads betting-basics.
- A tested `--publish-only` option allowed lessons to be sent using existing
  permissions. Publication claims/results are durable and prevent duplicate
  delivery. Existing messages were preserved; no pinning was claimed.
- Publisher source is committed at `7bccd48b6bc84ff43fdd19a99d5eca3f508ed1be`.
  It was executed once from a temporary maintenance directory in the existing
  worker, with SHA-256 `792cb66fdc922b2322411ccaca0ee25af54403d2301fb6c8b7f8ab21cb4f38fe`.
  The running worker image remains `410f42a`; its read-only application files were
  not changed. A future image deployment includes the new CLI option normally.

### Private ChatGPT connection backend

- API commit `97a398e0ebdf89eb319d2aeca90fae24b9cc69f1` is live on the existing
  Render API. Successful startup, migrations and readiness were verified.
- Added authenticated MCP over Streamable HTTP, fixed-client OAuth with PKCE,
  CSRF protection, short-lived access tokens, rotating refresh credentials,
  hashed credential persistence, revocation and research-only tool scope.
- Live OAuth protected-resource discovery returned HTTP 200; an unauthenticated
  MCP request returned HTTP 401. The official Python MCP client was exercised
  locally against initialization, tool discovery and actual model status.
- Endpoint: `https://jabbazi-research-api.onrender.com/mcp`.
  Predefined public client: `jabbazi-chatgpt`; no client secret.
- Private plugin JABBAZI Scanner `0.1.0` was created with the `scan-everything`
  skill and the deployed MCP endpoint. Plugin ID
  `plugins_6ab3f91ced948191a311a57e86f73def`, release
  `pluginrel_6ab3f91dd4148191843a9120f47d986d`, creator status `created`.
  [Open private plugin](https://chatgpt.com/plugins/plugins_6ab3f91ced948191a311a57e86f73def).
- **Regular ChatGPT remains unconnected.** Creating the plugin and deploying the
  endpoint do not establish account authorization. Developer mode is off; no
  successful call from Scanner Chat Migration has been verified. The existing
  private custom GPT connection documented in CHATGPT_SCANNER.md is separate.
- Neither MCP nor the plugin exposes wager placement, Discord publishing, owner
  administration or the ledger. Discord members do not receive scanner access.

## Verification

- GitHub workflow `35887174547` succeeded for worker commit `410f42a`.
- GitHub workflow `35888176001` succeeded for publisher commit `7bccd48`:
  **223 tests passed**, one deprecation warning, Ruff checks passed, API smoke
  checks passed, container build/CLI checks passed, PostgreSQL stack and disposable
  backup/restore checks passed, database-failure readiness checks passed.
- Regression coverage includes duplicate/alternate rows, full-slate pagination,
  doubleheaders, games without usable prices, all-page image delivery, owner
  verification, lesson idempotency and publishing without Manage Channel access.
- Live verification covers actual Discord image attachments and all 20 lesson
  contents. It does not cover a successful regular-ChatGPT OAuth flow yet.

## What the owner must still supply

1. **Consent to enable ChatGPT Developer mode** for the private custom MCP
   connection. The Browser skill requires confirmation at the time of changing
   a security-sensitive setting; it was not silently enabled.
2. **Secure account consent and private scanner key entry** in the native login
   flow. Use the scoped scanner key already created for JABBAZI, not the Odds API
   key and not the owner API token. Never paste any of these in chat. Then select
   the private connection in the intended regular scanner chat and verify one
   real model-status call followed by one scan, including returned model versions.
3. **Discord owner sign-in** to rename the existing channel to
   `📚｜learn-how-to` and update its topic. Lessons are already published. Alternatively
   the owner can make that single channel-name edit on the phone; no Administrator
   grant or broader bot access is necessary. No successful Discord browser login
   occurred during this work.

No additional data purchase, new paid infrastructure or OpenAI API key was needed
for these fixes. Future model validation still needs historical odds with lawful
decision-time coverage and adequate player/usage data for prop/TD models; those
are separate from connecting the existing research models.

## Remaining modeling limits

NFL and MLB score models remain **SHADOW_ONLY**, not approved actionable models.
NFL held-out Brier was about 0.2233 versus market baseline 0.2109; MLB lacked a
historical-odds comparison. Available probabilities must remain labeled as
experimental research. Reliable player-prop, anytime-touchdown, SGP dependence
and CFB model probabilities are unavailable. Teaching these bet types does not
make those models implemented or validated. No profitability or paid-picks
readiness is claimed.

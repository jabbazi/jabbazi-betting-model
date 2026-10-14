> Archived milestone document. See ../IMPLEMENTATION_STATUS.md and ../DEPLOYMENT.md for current behavior.

# JABBAZI GURU — Discord + three-sport launch kit

Prepared September 22, 2026. Brand: purple (#8B5CF6), charcoal (#111118), white.

## What is actually ready

| Component | Delivered | Still needed |
|---|---|---|
| Discord | Server layout; owner-checked setup script; private review publisher | Owner's Discord account, empty server, bot installation, permission check |
| MLB | Results adapter, independently tuned moneyline baseline, real trained artifact and holdout report | Historical odds, starter/bullpen/lineup features, calibration and prospective testing |
| NFL | Results adapter, independently tuned moneyline baseline, real trained artifact and holdout report | Timestamped odds, QB/injury/efficiency features, calibration and prospective testing |
| College football | CFBD data adapter, separate tuning grid and trainer, scanner registration | CFBD key, real training run, verified school mapping and venue context |
| Scanner | Three-league routing, authenticated API, existing price shopping and audit ledger | Current Odds API key, funded quota, host, operational checks |
| Memberships | Proposed free/VIP structure | Whop onboarding, pricing decision, paid-role connection and purchase/cancel tests |

Nothing has been deployed, no Discord messages have been sent, no membership
has been sold, and no wagers have been placed by this build.

## What the first models mean

These are team-strength Elo baselines for **pregame moneylines only**. MLB and
NFL were trained on real completed history from 2021 through the available
September 2026 results. Parameters are chosen on 2024, using earlier history;
2025 is the held-out evaluation season. Later 2026 games update the research
ratings without tuning the parameters or changing the 2025 test scores.

The college football trainer uses its own parameters, seasonal regression and
neutral-site handling. It has unit-test coverage, but no real CFB trained
artifact is included because the data key is not connected.

All three are deliberately `SHADOW_ONLY`: their estimates are research output.
Changing an artifact's approval flag does not enable paid betting alerts.
Market prices do not substitute for an independently validated prediction.

See `MODEL_REPORT.md` for the actual results. The NFL baseline did not beat the
market's probability scores. MLB has no historical market comparison yet.
Neither result establishes a profitable betting strategy.

## First steps for the owner

1. Create an empty Discord server named **JABBAZI GURU**, owned by your account.
2. Create a Discord application/bot in the [Developer Portal](https://discord.com/developers/applications).
   Install it into that server with Manage Channels and Manage Roles. The bot
   does not need Administrator. Keep its role above the roles it manages.
3. Request a [CollegeFootballData API key](https://collegefootballdata.com/key).
4. Connect your odds-data account and choose the cloud host. Store secrets in
   the host's secret settings or the local `.env`; never post them in chat.
5. Open the free community while the models run privately. Activate paid
   access only for services and coverage you can actually deliver.

The proposed $29/month founding tier is a pricing idea, not an activated plan.
Whop supports sports-picks products and Discord connections, subject to its
onboarding and current terms. Native Discord monetization has restrictions
on gambling-related communities. Billing through another service does not
remove Discord's general rules.

## Server layout

| Category | Channels | Access |
|---|---|---|
| START HERE | welcome, rules, how-to-read-picks, announcements | Everyone; staff post |
| COMMUNITY | free-picks, public-results, sports-chat, help | Everyone; chat/help open |
| VIP PICKS | daily-card, mlb-picks, nfl-picks, college-football-picks, parlays-and-alternates, price-updates, vip-chat | VIP and analysts; only vip-chat accepts member posts |
| OWNER DESK | scanner-review, model-health, operations | Owner, analysts, bot |

Roles: **JABBAZI VIP** (purple) and **JABBAZI Analyst** (gold). The server owner
retains control. Neither added role has global administrator permissions.
Assign Analyst only to trusted staff. Do not let the payment integration assign it.

The setup script creates or reconciles only its named roles and channels. It
does not delete unrelated channels, seed messages, create a Discord account,
or process subscriptions. Review its offline plan before applying it.

## Technical setup

Requires Python 3.12+. Run from the `scanner` directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
cp .env.example .env
python tools/discord_setup.py
```

On Windows, activate with `.venv\Scripts\Activate.ps1` and copy `.env.example`
using `Copy-Item .env.example .env`. The module name `jabazi` preserves the
existing code's import compatibility; the public brand is JABBAZI.

Configure the bot token, guild/server ID and owner/user ID in `.env`. The owner
check prevents accidental setup in someone else's server. Then:

```bash
python tools/discord_setup.py --apply
```

Open `scanner-review` in Discord and create an incoming webhook. Store its URL
and that channel's ID in `.env`. Verify the private channel is invisible to an
ordinary Free member and to a VIP test member before enabling delivery.

Configure `JABAZI_ODDS_API_KEY`. NFL and CFB estimates also require current
venue context keyed by Odds API event ID; see `scanner/config/README.md`.
CFB school names must map explicitly to the history identities.

```bash
# These use live odds quota. Preview does not post to Discord.
python -m jabazi.discord_review
# Post fresh experimental cards to the configured private review channel.
python -m jabazi.discord_review --send
```

Alerts are visibly marked RESEARCH / NOT A PICK, with no recommended stake.
The publisher rejects old prices, started events, and the wrong channel ID.
It records delivery reservations before sending, preventing silent retries
after uncertain network failures. Inspect any `needs_review` delivery row and
the Discord channel before an operator clears or retries it.

## Download and train each sport

Use today's UTC date for `--as-of`. Games starting on that date or later are
excluded even if an upstream score appears. These examples reproduce this build.

```bash
python -m jabazi history --sport mlb --as-of 2026-09-22 --output data/mlb_history.json
python -m jabazi train-baseline --sport mlb --input data/mlb_history.json --output models/mlb_baseline.json --holdout 2025

python -m jabazi history --sport nfl --as-of 2026-09-22 --output data/nfl_history.json
python -m jabazi train-baseline --sport nfl --input data/nfl_history.json --output models/nfl_baseline.json --holdout 2025

# Configure JABBAZI_CFBD_API_KEY first.
python -m jabazi history --sport cfb --as-of 2026-09-22 --output data/cfb_history.json
python -m jabazi train-baseline --sport cfb --input data/cfb_history.json --output models/cfb_baseline.json --holdout 2025
```

Re-download results and retrain after completed game days. This is not yet an
automated training service. Artifacts stop producing estimates when result
coverage is over five days old; this research limit is not evidence of roster
or injury freshness. Predictions cannot be generated for a quote preceding
the artifact's effective time.

## Hosting and recurring scans

`docker-compose.cloud.yml` includes an API service and a scanner service. Models
and reviewed context mappings are mounted read-only. Persistent scanner data is
stored in a named volume. Create `.env` and `config` before starting.

```bash
docker compose -f docker-compose.cloud.yml up -d --build
```

The scanner checks MLB, NFL and CFB every two hours. To enable private research
delivery during these passes, set `JABBAZI_DISCORD_REVIEW_ENABLED=true` only
after the destination/permission check. Refreshing result history and training
remains a separate operation. Two-hour scans are an initial research cadence;
timely paid alerts require a suitable odds budget and a tighter, tested schedule.

The API is not publicly exposed by this compose file. Connect the existing
website through an authenticated HTTPS proxy when deploying. Run one scanner
worker; move to a supported multi-worker database design before scaling.

## From baseline to paid product

1. **MLB:** add announced starter projections, bullpen availability, likely and
   confirmed batting lineups, handedness, park/weather effects, and a separate
   run-distribution model for spreads/totals. Features must be as known before
   each historical game, not final-season aggregates or postgame measures.
2. **NFL:** add QB status, opponent-adjusted EPA/success rates, offensive-line
   injuries, rest/travel, pace and weather. Develop spreads/totals separately.
3. **CFB:** add opponent-adjusted efficiency, QB/roster continuity, transfer and
   coaching changes, pace, travel and neutral-site context. Validate FBS/FCS
   handling explicitly. Initial scope is team markets, not CFB player props.
4. Join point-in-time sportsbook prices, fix all team/event identities, and
   compare predictions with the no-vig market on identical games. The Odds
   API provides timestamped historical snapshots on paid plans; estimate quota
   and confirm applicable data-use rights before purchasing a large backfill.
5. Use chronological development splits and retain an untouched evaluation
   period. Do not repeatedly tune against the reported 2025 test result. Paper
   trade live with timestamped prices, costs, availability, grading and CLV.
6. Validate each sport and market separately. A moneyline model does not
   validate a prop, alternate spread, or same-game parlay. Correlation and
   member-specific sportsbook availability need explicit handling.

The value proposition is timely research, clear prices, useful analysis, and
an honest full record. Publish losses alongside wins; use original published
picks and verified settlement, not edited screenshots, as performance proof.

## Sources and access

- [nflverse schedule data](https://nflreadr.nflverse.com/reference/load_schedules.html)
- [MLB Stats API documentation](https://docs.statsapi.mlb.com/)
- [CFBD API and client](https://github.com/CFBD/cfbd-python)
- [Historical odds snapshots](https://the-odds-api.com/historical-odds-data/)
- [Discord webhooks](https://docs.discord.com/developers/resources/webhook)
- [Discord guild/channel administration](https://docs.discord.com/developers/resources/guild)
- [Whop sports-picks setup](https://whop.com/blog/sell-sports-picks/)
- [Discord monetization policy](https://support.discord.com/hc/hi-in/articles/10575066024983-Server-Monetization-Policy)

The included datasets are research snapshots, not a grant of commercial feed
or redistribution rights. Review each provider's terms for the paid product.

# JABBAZI Discord research tools

The gateway bot was deployed and live-verified on September 23, 2026: !vip replied
with a real heartbeat, !cheatsheets nfl delivered a research export, and automatic
delivery published all three sports after a scan. The newer PNG format below has
local test coverage; verify it after deploying this revision. No official picks
are published by these commands.

- `!vip` is disabled in member Discord. The scanner remains owner-only.
- `!cheatsheets` in cheat-sheets returns MLB/NFL/CFB PNG research cards.
- `!cheatsheets mlb`, `!cheatsheets nfl`, `!cheatsheets cfb` select one sport.
- Each sport has three categories. Game sheets group one matchup together,
  choose a representative threshold per market, and preserve unpriced feed events
  as unavailable. Duplicate quote/rung rows cannot crowd out other games.
  Up to 24 matchups fit on a page; the default command and automatic delivery
  send **every page**. `!cheatsheets nfl 2` is an optional specific-page request.
  Coverage means all events returned by scanned odds feeds, not a separately
  verified league calendar. A large slate may require more than three images. Empty categories are explicitly unavailable.
- NFL categories are game lines, player props, and anytime touchdowns. Market
  probabilities never stand in for missing model forecasts. The bot copies the
  configured server icon to its own avatar on startup when the icon changes.
- The scanner archives an immutable sheet after each completed scan. The gateway
  checks once per minute and publishes a new recent sheet once. Failed scans produce
  DATA UNHEALTHY, not the previous successful sheet. Missing/older-than-three-hour
  sheets are unavailable. Prices inside a sheet remain historical observations.
- Columns separate probability edge and expected ROI. Missing model estimates stay
  empty. Exports are capped at 10,000 source candidates and flag truncation.
- Channel-wide 30-second command throttling and durable delivery claims prevent spam.
  A send with uncertain outcome is recorded as needs_review and is not retried blindly.
- CSV formula prefixes are escaped. Mentions are disabled. User message content,
  credentials, and raw provider failures are not logged.

## Deployment prerequisites

Optional branding: configure `JABBAZI_DISCORD_BRAND_CHANNEL_IDS` as a comma-separated
allowlist and `JABBAZI_DISCORD_BRAND_GIF_URL` as the uploaded Discord CDN GIF URL.
Only a server-owner post mentioning the actual bot (or exactly `!guru`) triggers
the GIF response. The response never mentions everyone or a role. It claims each
message before sending to prevent repeat delivery. This feature is not live; the
approved animated logo still needs to be uploaded and the bot needs channel access.
Typing a display name as plain text is not a Discord bot mention.

1. Owner supplies JABBAZI_DISCORD_BOT_TOKEN in the hosting secret manager.
2. Review/enable the Message Content intent in the Discord Developer Portal; prefix
   commands require it. Do not enable member/presence intents.
3. Give the JABBAZI Research bot View Channel, Read Message History, Send Messages,
   Embed Links and Attach Files **only in the two tool channels**. No Administrator.
   Review this access change with the owner before applying it.
4. Explicitly deny @everyone View Channel on both targets. Approved VIP/analyst
   viewer role IDs must be listed in JABBAZI_DISCORD_VIEWER_ROLE_IDS (comma-separated).
5. The Docker image installs `.[discord]` and the worker starts the optional bot
   subprocess when JABBAZI_DISCORD_COMMANDS_ENABLED=true. They share the existing
   database and service; no additional paid service is needed. The worker reports
   subprocess health and terminates it on shutdown. It does not restart-loop a
   failed bot. The bot can also run separately with `python -m jabazi.discord_bot`.

Required environment variables (no secret values in git):

```
JABBAZI_DISCORD_COMMANDS_ENABLED=false
JABBAZI_DISCORD_GUILD_ID=1552043745153650840
JABBAZI_DISCORD_OWNER_ID=<verified owner ID>
JABBAZI_DISCORD_STATUS_CHANNEL_ID=1552128609869758484
JABBAZI_DISCORD_SHEETS_CHANNEL_ID=1552129051789885553
JABBAZI_DISCORD_VIEWER_ROLE_IDS=<reviewed role IDs, or empty for owner-only>
JABBAZI_DISCORD_BOT_TOKEN=<hosting secret>
JABBAZI_PLATFORM_DATABASE_URL=<hosting secret>
```

Verify before advertising commands as live: owner identity, private target permissions,
bot connection and intent, !vip response, a real archived scan exported into all three
CSV files, one automatic post, no duplicate after process restart, and suppression
after stale data or a failed scan. No production Discord message test has run yet.

## Server content convention

Only #jabbazi-picks inside VIP PICKS contains official issued JABBAZI plays. The
MLB/NFL/CFB picks and VIP parlays channels contain member contributions. All Sports &
Research channels are discussion. A bot research sheet is not an official pick.

## Learning channel

The owner-approved learning curriculum and idempotent publisher are documented in
[discord/LEARNING_CHANNEL.md](discord/LEARNING_CHANNEL.md).

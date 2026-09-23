# JABBAZI Discord research tools

The gateway bot is implemented but **not deployed or live-verified**. Installing the
Discord application alone does not run this process. Existing webhook review is
unchanged. No official picks are published by these commands.

- `!vip` in scanner-status reports the persisted worker heartbeat; it never grants a role.
- `!cheatsheets` in cheat-sheets returns MLB/NFL/CFB CSV research snapshots.
- `!cheatsheets mlb`, `!cheatsheets nfl`, `!cheatsheets cfb` select one sport.
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
5. Install with `pip install '.[discord]'`. Run `python -m jabazi.discord_bot` in an
   approved persistent service sharing the production database. Do not add a paid
   service without cost approval. Enable JABBAZI_DISCORD_COMMANDS_ENABLED=true only
   after all checks. Deploy the scanner code as well to begin sheet archiving.

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

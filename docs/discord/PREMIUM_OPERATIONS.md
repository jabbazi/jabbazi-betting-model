# JABBAZI GURU Discord operations

## Production contract

The Discord layer is a presentation and entitlement surface over the audited JABBAZI
database. It does not manufacture probabilities, place wagers, or promote model stages.

### Daily sheet

- One official moneyline sheet per America/Chicago calendar day.
- Worker attempts a fresh quick scan during 09:00-09:14 local time.
- The first healthy sheet is frozen immutably as `daily_moneyline_sheet`.
- Discord delivery is claimed before network send to prevent duplicate reposts after
  ambiguous failures.
- `/cheatsheet` retrieves the frozen record; it never launches another scan.
- Later material changes are alerts/research updates, not silent edits to the frozen sheet.

### Official picks

`#jabbazi-main-card` only accepts candidate records whose scanner decision is BET_NOW,
stake is positive, and `model_can_influence_cash=true`. WATCH, PRICE CHECK, SHADOW_ONLY,
VALIDATING-only, and unhealthy candidates cannot render as official picks.

### Best-2

The Best-2 channel displays the protected external-sheet research lane. External claimed
units are metadata only. PRICE CHECK remains visible until exact combined sportsbook
pricing exists. The Discord publisher cannot turn the research candidate into a placed bet.

### VIP

Billing systems write entitlement evidence through the authenticated
`POST /v1/discord/entitlements` endpoint. The API synchronizes the configured VIP role
for that exact Discord member. The worker reconciles known entitlement records every five
minutes so expiration removes access. No payment secrets are stored in Discord.

Plan prices and payment links are intentionally not hard-coded. Configure them only from
the authenticated billing provider.

## Required Discord configuration

The bot requires:

- `JABBAZI_DISCORD_BOT_TOKEN`
- `JABBAZI_DISCORD_GUILD_ID`
- `JABBAZI_DISCORD_OWNER_ID`
- `JABBAZI_DISCORD_STATUS_CHANNEL_ID`
- `JABBAZI_DISCORD_SHEETS_CHANNEL_ID`
- `JABBAZI_DISCORD_VIP_ROLE_ID`
- `JABBAZI_DISCORD_VIEWER_ROLE_IDS`

Optional publication targets:

- `JABBAZI_DISCORD_MAIN_CARD_CHANNEL_ID`
- `JABBAZI_DISCORD_BEST_TWO_CHANNEL_ID`
- `JABBAZI_DISCORD_RESULTS_CHANNEL_ID`

Enable the gateway only after IDs and permissions are reviewed:

`JABBAZI_DISCORD_COMMANDS_ENABLED=true`

Do not grant Administrator. The bot needs only the channel/role/message permissions used by
the configured features, and its role must sit above VIP if it manages VIP membership.

## Server bootstrap

`python tools/bootstrap_discord.py`

is a dry run. It reports missing roles/categories/channels and changes nothing.

After reviewing the target guild:

`python tools/bootstrap_discord.py --apply`

creates only missing objects. It does not delete, rename, overwrite, or mass-edit existing
server content.

## Security notice to pin

**JABBAZI STAFF WILL NEVER DM YOU ASKING FOR CRYPTO, PASSWORDS, SPORTSBOOK LOGIN
INFORMATION, OR YOUR DISCORD LOGIN.**

## Responsible betting notice

JABBAZI is research and entertainment, not guaranteed income. No wager is guaranteed.
Bet only money you can afford to lose, use consistent units, do not chase losses, and take
breaks when needed.

## Manual authorization still required

The repository cannot authenticate itself to a Discord guild or payment account. Before
the system can mutate the live server, the owner must supply/authorize the Discord bot and
guild configuration. Paid subscriptions additionally require an authenticated payment
provider and owner-approved products/prices.

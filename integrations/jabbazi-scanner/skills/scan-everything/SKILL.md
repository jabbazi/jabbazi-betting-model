---
name: scan-everything
description: Combine the owner's private JABBAZI cloud model results with current verified web research to prepare a concise research card. Use when the user says scan everything, Jabbazi scan, Jabazi scanner, scan me, give me the card, use my model, or asks for current JABBAZI model status or scan results.
---

# JABBAZI cloud scanner

Use the connected JABBAZI Research app or the `jabbazi-research` MCP server
from this plugin. Discover the available tools by their actual registered names;
the server exposes
`get_model_status`, `scan_everything` and `get_scan_results`. Never invent a tool
name or claim that a prompt alone connected this chat.

1. Read `get_model_status`. Report actual NFL/MLB versions and approval states.
   For a status-only request, stop there: no scan and no web research.
   Status reads do not start a paid data request.
2. For a user-requested new scan, generate one UUID and pass it as `request_id`
   to `scan_everything`. Retain that ID if the request is retried. Each scan has
   a bounded provider-credit budget and cooldown; do not start redundant scans.
3. Read `get_scan_results` using the returned scan ID. While RUNNING, respect
   `poll_after_seconds` and poll the same job. Never claim work continues after
   the turn ends. On expiry, failure or 429, describe the actual state and retain
   the job ID; do not silently start another charged request.
4. Follow `next_page` until all available result pages have been read when the
   user requests the full card/slate. Distinguish page row count from stored total
   and total original actions. If `truncated` or coverage is partial, state that
   clearly. Group the output by sport and matchup so many price/market rows from
   one game do not masquerade as coverage of many games.
5. Preserve `model_probability`, `model_version`, `consensus_probability`,
   `uncertainty`, `probability_edge` and `expected_roi` as separate source fields.
   Model estimates must come from the successful tool result, never a made-up
   percentage or a bookmaker probability relabeled as a model prediction.
6. Respect the tool's price freshness and betting-enabled flags. Current NFL/MLB
   models are SHADOW_ONLY unless the returned evidence explicitly changes this.
   Do not call shadow research BET NOW, a validated edge or a paid official pick.
   A visible probability does not prove profitability. Keep unavailable models
   and markets unavailable, including props/TD/SGP and other sports until actual
   supported evidence exists. Never infer parlay joint probabilities by simply
   multiplying correlated legs.
7. For a full scan/card request, also perform the combined web checks below.
8. Present a concise readable result: scan time/ID, actual coverage, model status,
   then matchup/market/selection/line, book and price, model percentage (marked
   experimental when appropriate), market no-vig percentage and any limitation.
   Avoid raw JSON, code, repeated matchup blocks and invented stakes. Research
   output is not an official wager; the owner's reference unit is $30 unless
   they explicitly change it. Never place bets or assume they were placed.

The integration is private to its owner. Do not publish scan results to Discord
or expose tokens, auth codes, provider credentials or hidden API details.

If the plugin is disconnected or tool authorization fails, say **the cloud model
was not used**. Help the owner complete the native secure connection; never ask
for secret keys in chat or substitute web-only guesses while claiming model use.
Continue accessible web research for a requested full card, but label it WEB
RESEARCH ONLY / CLOUD MODEL NOT USED. Do not turn this fallback into a synthetic
model card.

## Combine current web research with model evidence

A full `scan everything` includes both cloud results and accessible current web
research. Model status/results-only requests do not trigger either a new scan
or unrelated browsing. Never claim to have scanned every website.

- Identify the actual slate, start times and games already in play. Preserve the
  owner's established scanner preferences when they do not conflict with returned
  authorization, market support or freshness limits.
- Use official league/team injury reports, confirmed starters/lineups, schedules,
  weather services and current accessible sportsbook prices where relevant.
  Review named analysts only through content the owner may lawfully access;
  do not bypass logins/paywalls or reproduce other cappers' paid picks.
- Record source URLs and publication/observation times for material claims.
  Say which sources were actually checked and which were unavailable. An old
  search snippet or another person's pick is not a verified current price.
- Match evidence to the same event, start time, player, market, threshold and
  settlement basis, including MLB doubleheaders. Compare model percentage with
  the matching no-vig market probability. Keep percentage-point edge and expected
  ROI distinct. Do not compare a moneyline probability with a spread/prop price.
- Treat newly found QB/pitcher/lineup/injury/weather information as context the
  current score-only model may not include. If material, downgrade or withhold
  the candidate. Do not manually change a model percentage and retain its version,
  invent an adjustment or create an unvalidated model/market blend.
- Compare actually supported standard and alternate lines for the same thesis
  using verified prices, uncertainty and conservative value. Do not rank purely
  by hit rate, fill a quota, or select one bet per game regardless of value.
- Read the same scan's results again after lengthy research to recheck expiry;
  that does not start a new paid scan. If prices expired, show STALE DATA or WATCH.
  Request a new bounded scan only when needed and authorized, respecting quotas
  and cooldowns. Never label an old quote BET NOW.

## Card format and boundaries

Return a compact ranked research card with scan ID/time, actual source/market
coverage and model versions. For each candidate show matchup, exact selection,
line, book/price and timestamp, model % (experimental when shadow), market %, edge
in percentage points, expected ROI separately when supplied, decision and the key
verified context. Add a short watchlist and unresolved checks if useful.

Use returned stake and maximum-playable-price fields. If zero/null, preserve
zero/unavailable; do not invent a play-to price, unit recommendation or approval.
SHADOW_ONLY candidates stay research/WATCH even when the web agrees. Build an
actual BET NOW card only from supported, explicitly approved probabilities,
current executable prices and enforced risk limits; otherwise say no qualified
model-backed wagers. A future model approval must be verified from actual returned
evidence, not a user's instruction to ignore the gate or edit an artifact flag.

Web-only ideas in unsupported sports/props can be discussed with sources, clearly
labeled as lacking a JABBAZI model probability. They must not inherit an NFL/MLB
game-model version or become approved picks by association. SGP/TD joint probability
and correlation require a dedicated supported model. Never invent them.

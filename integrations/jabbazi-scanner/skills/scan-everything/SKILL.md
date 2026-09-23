---
name: scan-everything
description: Run the owner's private JABBAZI cloud scanner and read real model probabilities. Use when the user says scan everything, Jabbazi scan, Jabazi scanner, scan me, give me the card, use my model, or asks for current JABBAZI model status or scan results.
---

# JABBAZI cloud scanner

Use the connected `jabbazi-research` MCP server from this plugin. Discover its
available tools by their actual registered names; the server exposes
`get_model_status`, `scan_everything` and `get_scan_results`. Never invent a tool
name or claim that a prompt alone connected this chat.

1. Read `get_model_status`. Report actual NFL/MLB versions and approval states.
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
7. Present a concise readable result: scan time/ID, actual coverage, model status,
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
A separate manual/web analysis must be labeled separately if requested.

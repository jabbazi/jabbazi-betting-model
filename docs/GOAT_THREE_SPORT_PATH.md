# JABBAZI V6 — NBA/NFL/NHL GOAT-first integration

**Status: development / RESEARCH_ONLY.** The account owner reports GOAT subscriptions for NBA, NFL, and NHL and only one BALLDONTLIE Sports API key. This is a user-reported entitlement, **not** live authenticated verification of all three sport-specific paid prop endpoints.

## Primary integration (no LAB subscription required)

- Use the existing `JABBAZI_BALLDONTLIE_API_KEY` solely for authenticated NBA/NFL/NHL Sports API stats and sportsbook player-prop quotes. Preserve it in the existing private Render environment; do not copy to CI, logs, or chat.
- Use the existing JABBAZI NBA/NFL/NHL player-distribution artifacts for **research-stage** exact-line probability development. Do not treat the GOAT sportsbook quote, no-vig market prior, or LAB model confidence as a calibrated JABBAZI hit probability.
- The private `POST /v1/chatgpt/boost-goat-feed-diagnostic` is a sport-scoped, bounded, aggregate-only provider check. It requires only the Sports API key, discovers games for the requested date, and checks the selected sport's actual paid prop responses. It does not require LAB, approve any market, or return raw licensed quotes.
- The existing `tools.boost_live_acceptance_matrix` performs the three-sport independent-date check from an authorized private runtime, including NHL.
- `JABBAZI_BALLDONTLIE_LAB_API_KEY` and LAB-to-odds joins are **optional research extensions**, not prerequisites for the GOAT-first JABBAZI model pipeline. If LAB is absent, do not call it or mark GOAT feed coverage failed for that reason.

## Required private operator verification

Run on the exact feature commit in an authorized environment already holding the Sports API key. Choose **real future games** for each sport, not arbitrary placeholders. Different sports can have different eligible dates.

```bash
python -m tools.boost_live_acceptance_matrix --nba-date YYYY-MM-DD --nfl-date YYYY-MM-DD --nhl-date YYYY-MM-DD --max-games 5 --request-budget 30
```

Record a redacted, UTC-timestamped report: authenticated status, eligible games, complete pagination, valid fresh quote rows, market breadth, rejected rows, and whether all three sports had nonempty eligible coverage. An empty date or missing games is **not** proof of failed entitlement; retry a known upcoming eligible slate rather than fabricate rows.

## Probability approval is separate

For each player-market line, require an identified and versioned JABBAZI distribution, point-in-time player/game/stat mapping, pregame features, out-of-sample testing and genuine prospective settled outcomes. NBA/NHL joint SGP probability requires immutable frozen exact-ticket forecasts, independent combined sportsbook quotes, and event-independent prospective calibration and review. Until approved, the scanner must show `VALIDATING`/`RESEARCH_ONLY`, not a verified edge or wager recommendation.

**No merge, production deployment, Discord publication, or wagering approval** is authorized by passing the feed diagnostic or development CI alone.


## Market-category reconciliation (development)

The private GOAT diagnostic now includes `jabbazi_market_alignment`, a de-identified mapping of **documented Sports API prop_type categories** into the existing JABBAZI NBA/NFL/NHL player-model market taxonomy. The map is explicit and sport-scoped, not a fuzzy name match. Unsupported categories such as NFL first touchdown and NHL first goal remain `UNMAPPED` rather than receiving a fabricated player model. It reports mapped and unmapped quote counts without player IDs or prices.

**Category alignment is not player-level integration or calibration.** The remaining necessary steps are: authenticated complete live paid prop coverage; verified player/game identity crosswalk, frozen pregame feature snapshots, actual model artifact/version and exact sportsbook line; then independent prospective settlement/calibration and correlation-aware joint validation. The alignment diagnostic always reports `model_hit_probability_verified=false`, `joint_probability_verified=false`, `betting_enabled=false`. No production release should be inferred from mapped quote counts.

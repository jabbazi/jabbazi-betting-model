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


## Player/game/line to pregame feature join audit

`src/jabazi/boost_goat_feature_join.py` provides a **research-only**, aggregate audit of exact BALLDONTLIE game/player IDs, sport-scoped mapped market, identical numeric threshold, a nonempty versioned JABBAZI model, and an explicitly reviewed frozen pregame feature snapshot. It rejects missing identity attestations, ambiguous feature rows, mismatched lines, stale vendor quotes and duplicate sportsbook offers. Its result contains counts and rejection reasons only; it never returns licensed player rows or computes probabilities. It must not be treated as an independently verified crosswalk just because an input flag says verified: the source crosswalk and freeze must be audited against actual provider records and immutable model evidence.

The authenticated Render Shell supplied by the owner has demonstrated NBA and NFL paid player-prop access, but **no authenticated live player-to-feature joins** have been executed. No GOAT source data has been promoted into production model inference. NHL remains HTTP 401 on its games endpoint. A previous CI run uncovered legacy tests expecting the incorrect unprefixed NBA routes; those tests were updated to the real authenticated `/nba/v1` and `/nba/v2` paths. All current-head CI must finish before any release consideration.


## Private NBA/NFL exact feature acceptance (after GOAT endpoint authentication)

On an **authorized private checkout of this feature commit**, with the existing Sports API key already configured, use a *locally reviewed* frozen feature metadata JSON file (not committed or pasted into chat). Each row must be independently crosschecked against actual BALLDONTLIE game/player IDs and a genuine immutable JABBAZI pregame model feature snapshot. Do not create or mark attestation flags as true without that audit.

```bash
python -m tools.verify_goat_feature_join --sport NBA --game-id VERIFIED_NBA_GAME_ID --feature-file /private/verified_nba_features.json --request-budget 20
python -m tools.verify_goat_feature_join --sport NFL --game-id VERIFIED_NFL_GAME_ID --feature-file /private/verified_nfl_features.json --request-budget 20
```

The operator must replace the symbolic game IDs with actual positive integer provider IDs from the eligible slate and provide existing private files. No sample JSON file is supplied because synthetic attestations would create misleading acceptance evidence. The command returns only aggregate join counts and errors; success means **exact model input matching observed**, not a model prediction, a validated edge, or wagering approval. It is **not available on the older production checkout** and should not be used to modify or replace the production service. NHL remains blocked by its HTTP 401 games response.

**Next required engineering step:** establish the independently reviewed, point-in-time player identity crosswalk and feature snapshots; only then wire versioned JABBAZI inference to exact-line model research and validate against independent prospective outcomes.


## Cross-provider identity integrity: mandatory evidence before live joining

The existing NBA feature collector uses **ESPN athlete IDs** and SportsDataverse historical player IDs, while BALLDONTLIE sportsbook props use **BALLDONTLIE player IDs**. NFL model features similarly originate from nflverse/other sources. These are different namespaces: equal names or numerically equal IDs are **not** a verified crosswalk. No live NBA/NFL player-to-feature matching has been demonstrated merely by paid odds access.

The exact feature join now requires a reviewed `identity_crosswalk_sha256`, `feature_source_sha256`, canonical `playerfs-...` feature snapshot reference, and explicit `event_starts_at` strictly after the feature freeze. The hashes are structural provenance fields, not proof that their referenced content exists or was audited. **Never fill these with dummy values or turn verification flags on to make tests pass.** Verify the referenced immutable crosswalk, original vendor player/game IDs, ESPN/nflverse identity, roster/team and event timestamps in a private environment. Then measure actual join counts and rejection categories using the private acceptance command. This remains research-only until independent exact-line inference and prospective validation pass.

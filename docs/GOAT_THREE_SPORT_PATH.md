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


## NBA/NFL provider-ID crosswalk manifest validator

`src/jabazi/boost_identity_manifest.py` now audits a private operator-supplied manifest linking BALLDONTLIE player/game IDs to the **correct source namespace** (ESPN for NBA, NFLVERSE for NFL). It enforces review timestamps preceding the scheduled game, source-record checksums, deterministic manifest fingerprints, and rejects duplicate/conflicting BALLDONTLIE identities. Output contains only counts and reason codes. No names or raw IDs leave the private environment.

**Critical limitation:** a syntactically valid checksum, `independent_source_reviewed=true`, or passing unit test does NOT establish that two real-world player identities correspond. The independent source records must be fetched, compared, and audited in the authorized private runtime. Until those actual records are supplied, `independent_provider_truth_confirmed_by_runtime=false`, and model inference/wagering remain blocked.


## Automated NBA/NFL cross-provider roster candidate generation (private, read-only)

A new operator command, `tools.prepare_goat_roster_candidates`, reduces manual source preparation. It retrieves fresh, eligible GOAT props for **one authentic upcoming game**, fetches the distinct BALLDONTLIE player directory records, and compares them with a current **ESPN NBA roster** or **nflverse NFL 2026 season roster**. The source adapters are `boost_nba_espn_roster.py` and `boost_nfl_nflverse_roster.py`. The nflverse release asset `roster_2026.csv` exists and was updated 2026-10-29; the source schema includes GSIS IDs, team, position, name, and jersey.

Example operator commands (symbolic placeholders are **not** real IDs or kickoffs):

```bash
python -m tools.prepare_goat_roster_candidates --sport NBA --game-id VERIFIED_NBA_GAME_ID --starts-at VERIFIED_NBA_START_ISO8601 --max-prop-pages 25 --request-budget 40
python -m tools.prepare_goat_roster_candidates --sport NFL --game-id VERIFIED_NFL_GAME_ID --starts-at VERIFIED_NFL_START_ISO8601 --max-prop-pages 25 --request-budget 40
```

Only run inside an authorized **private checkout of the exact tested feature commit** with the existing Sports API key in the environment. Do not run against the old production checkout, change production branch, or paste the key. The command prints **counts and rejection reasons only**, not raw players, game IDs, source rosters, or licensed sportsbook quotes. An optional `--save-private-candidates /private/new-file.json` writes a new 0600-permission local file and refuses to overwrite an existing file. Never upload that file to a public repository or chat.

Candidate matching requires normalized name, team, jersey, unique identities, and NFL position agreement, plus a bounded pregame source snapshot. **Candidates are not verified identity crosswalks.** Names and jerseys can coincide or change; independent original-record review, event/team validation, and verified feature snapshots remain required before any model input can be accepted. The command never computes a hit probability, SGP EV, or wagering approval.

The documented NBA/NFL GOAT category mapping now includes NBA blocks, steals, double-double, and NFL passing attempts/completions where corresponding JABBAZI model market types exist. This expands possible research coverage; it does not prove the model artifacts are trained, calibrated, or applicable to every quote.


## Prospective calibration pipeline recovery (NBA/NHL)

A critical circular gate was corrected in `PlayerPropModel.estimate`: **verified pregame feature inputs** are no longer overwritten with the model's **wagering approval** status. Previously, a VALIDATING model with genuine verified inputs still reported `production_inputs_verified=false`, so the prospective evaluator rejected every forecast before it could collect the samples needed for approval. Input integrity and model promotion are now independent: research predictions can be frozen and evaluated while `approved_for_betting=false`.

The prospective freezer previously hardcoded NFL/MLB markets and silently omitted every NBA/NHL player market. It now uses the canonical `PLAYER_PROP_MARKETS` registry, allowing supported NBA/NHL research forecasts to be frozen before kickoff. The existing `validation_report` still requires authentic pregame inputs and separately archived final results; no sample count is manufactured.

A new `boost_nba_final_labels.py` extracts the 12 NBA player-market outcomes from final BALLDONTLIE boxscores using the **same target definitions** as JABBAZI NBA training. It rejects DNP/unknown minutes, missing stats, incoherent or duplicate boxscores, nonfinal games, postgame crosswalk review and foreign identities. It does not interpret missing data as zero.

`tools.audit_nba_prospective_results` is a private, **dry-run-by-default** acceptance/settlement utility. With an independently reviewed local crosswalk, a completed GOAT NBA game, and existing immutable pregame forecasts in the private JABBAZI database, it reports eligible labels and matches. **No database writes happen by default.** An explicit `--commit-reviewed-results` operator flag is required to archive results, and only previously frozen, trusted, exactly matched event/player/market forecasts are eligible. The tool does not generate missing forecasts retroactively, fabricate closing prices, promote models, or place wagers.

```bash
python -m tools.audit_nba_prospective_results --game-id VERIFIED_FINAL_NBA_GAME_ID --date YYYY-MM-DD --reviewed-crosswalk-file /private/reviewed_nba_crosswalk.json
```

The command is only available from the exact tested feature checkout in a private authorized runtime with existing `DATABASE_URL` and `JABBAZI_BALLDONTLIE_API_KEY`. Do not commit or paste the crosswalk file, keys, player rows or source stats into chat. No production result writes or prospective validation were performed during development. Genuine outcomes over many independent games and an independent market baseline remain necessary for approval.


## Exact-line fitted research inference and safety status

`boost_goat_research_inference.py` now supplies a **read-only, sport-scoped** adapter that can evaluate an actual BALLDONTLIE player-prop threshold with the existing fitted JABBAZI NBA/NFL distribution. It requires an independently reviewed cross-provider mapping, an immutable and **production-input-verified** pregame feature snapshot, exact event/player/market/line identity, a current licensed quote, and a matching versioned fitted model. It returns **research-only** over/under (or binary yes) probabilities, never a sportsbook-derived model probability, executable EV, or approved SGP. Whole-number push-capable lines are rejected until settlement-aware pricing is supported. Unverified SportsDataIO provenance or `research_only=true` inputs fail closed.

The core player result archiver also rejects future-dated observations and unsupported settlement statuses, preventing a future timestamp from being accepted as completed prospective evidence. No fabricated forecasts, future results, or model promotion are authorized. Unit tests use synthetic fixtures only; live provider-to-model inference still needs private acceptance.

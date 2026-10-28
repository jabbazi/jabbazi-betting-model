# Paid NBA/NFL/NHL player-data scanner — acceptance gate (2026-10-28)

**State: DEVELOPMENT / RESEARCH_ONLY. Never mark as a production-verified hit-probability feed without independent observed evidence.** This work extends PR #80 without touching normal \`SCAN EVERYTHING\`, existing Discord authorization, production credentials, database, or services.

## Data source contract: do not conflate feeds

1. BALLDONTLIE **Sports API player_props** provides sportsbook lines and prices for supported NBA/NFL/NHL events. It is not a provider of calibrated player hit probabilities. Live full-slate entitlement requires per-sport authenticated checks.
2. BALLDONTLIE **LAB API** offers saved player-prop *models/predictions* for NBA and NFL, plus MLB. Its published documentation states that **NHL LAB supports game models only**. It is incorrect to call NHL sportsbook odds "LAB NHL player hit probability."
3. LAB saved prediction \`predicted_value\` is a model signal/score; neither it nor LAB \`confidence\` may be shown as a projected stat total or an independently calibrated probability of clearing an exact line. \`confidence\` measures signal strength. The VIP panel shows these quantities separately and always sets \`model_hit_probability = null\` until separately validated.
4. JABBAZI NBA/NFL/NHL player models are a **third source**, with model versions, features and prospectively validated line-specific probabilities. The LAB model reader does not promote JABBAZI artifacts.

Official docs:
- https://lab.balldontlie.io/docs/ (Model Types, Live Predictions)
- https://lab.balldontlie.io/docs/api/ (Authentication, subscriptions, list models, list predictions)

## Implemented (feature branch only)

- \`GET /v1/vip/paid-player-models?sport=NBA|NFL|NHL&slate_date=YYYY-MM-DD\` uses the pre-existing VIP session authorization and service key. Quota-limited, pagination-aware LAB reads are done **on demand**. No paid request runs on ordinary scans. Missing subscription, no rows, invalid pagination, or unsupported NHL fail closed.
- VIP scanner board and sport pages link to separate paid-player-model research. No prices are labeled as model probabilities. Nothing is forwarded to wagers, +EV, public Discord channels or normal scan output.
- \`python -m tools.verify_paid_lab_access --sport ALL --date YYYY-MM-DD\` runs a **read-only provider acceptance diagnostic only in a private authorized environment**. It prints aggregate counts and status, never secrets, model IDs or raw licensed records. Exit code 0 means NBA/NFL supported sources returned complete bounded API responses and the expected NHL unsupported status; it **does not** mean models/predictions are present, calibrated, or deployable.

## Private operator acceptance

An authorized private runtime with existing BALLDONTLIE secret and the exact PR head must execute:

\`\`\`bash
python -m tools.verify_paid_lab_access --sport ALL --date YYYY-MM-DD
python -m tools.boost_live_acceptance_matrix --nba-date YYYY-MM-DD --nfl-date YYYY-MM-DD --nhl-date YYYY-MM-DD --max-games 25 --request-budget 90
\`\`\`

Use verified upcoming dates independently for each sport. These two checks serve different products: LAB saved models versus Sports API live sportsbook props. Record the exact commit, UTC observation, sanitized per-sport counts, any 401/403/429 failures, nonempty eligible-game coverage and a clear verdict. The user should not be asked to paste any key into chat. The current hosted Render connector cannot open a private shell, so mock GitHub Actions runs must not be substituted for authenticated evidence.

A future NBA/NFL/NHL **player hit-probability** release also requires a documented actual model-probability source for each sport, a point-in-time player/game/market/line mapping, current feed freshness, archived independent prospective game outcomes, calibration, and a passing production VIP/Discord verification. NHL LAB player props cannot satisfy that gate. If any element is absent, the scanner must show UNAVAILABLE/PASS, not an invented hit percentage or BET NOW.

**Do not merge/deploy feature PR #80 solely on successful development CI.** Keep existing Render API/Worker on the current verified production commit until live acceptance and the separate Discord delivery blocker are resolved.

## Authentication correction and strict release status

NBA/NFL LAB prediction access is **not** authenticated through the regular BALLDONTLIE Sports API key. The implementation now reads a distinct environment variable `JABBAZI_BALLDONTLIE_LAB_API_KEY`, reserved for an authorized LAB PRO or ALL-ACCESS credential. The existing `JABBAZI_BALLDONTLIE_API_KEY` remains the Sports API odds/props credential and is never silently reused for LAB. If LAB is not connected, this research route fails closed; do not buy a subscription or change secrets without authorization.

The read-only LAB acceptance reports `lab_endpoint_authenticated=true` after a complete paginated response even if no saved rows exist. It reports `saved_player_predictions_observed=true` only when a supported sport has actual saved player-prop predictions. Its exit 0 requires a nonempty NBA/NFL prediction set for each requested supported sport, but **still does not establish JABBAZI calibrated hit probabilities or wagering approval**.

NHL LAB player-prop models remain unsupported. Verify NHL **Sports API** prop coverage separately using `python -m tools.boost_live_acceptance --sport NHL --date YYYY-MM-DD` or the three-sport odds matrix.

No private service secret was read or modified during development. The available GitHub and Render tools cannot execute authenticated commands inside the production service or its private database, so live acceptance remains pending. For a valid JABBAZI hit chance, require exact player/event/market/line, pregame data, model version, external benchmarks, timestamped prospective outcomes, and passing calibration gates. Never map LAB signal strength or market-implied prices to an approved player hit percentage.

## Subscription and identity clarification

BALLDONTLIE states that its **Sports API ALL-ACCESS** subscribers automatically receive LAB Pro access; other Sports API plans do not establish LAB entitlement. A LAB API key must still be retrieved from the authorized LAB account and configured privately, not pasted into chat. See https://lab.balldontlie.io/ and https://lab.balldontlie.io/docs/api/. Do not buy an additional subscription before checking existing entitlement.

A saved LAB prediction is displayable only with a valid model ID, game ID, player ID, and numeric signal. Missing identities are counted in aggregate as `rows_rejected_missing_identity_or_signal`, excluded from the VIP research rows, and cannot make the acceptance gate pass. Even a complete, nonempty LAB response is not a calibrated exact-line hit probability. NHL sportsbook props must be checked through the separate Sports API acceptance matrix.


## Private exact-join acceptance command (NBA/NFL)

On an authorized shell with the **feature branch checked out**, and with the two distinct existing credentials available only as private environment variables:

```bash
python -m tools.verify_paid_join --sport NBA --date 2026-10-28 --game-id <verified-bdl-nba-game-id>
python -m tools.verify_paid_join --sport NFL --date 2026-10-28 --game-id <verified-bdl-nfl-game-id>
python -m tools.boost_live_acceptance --sport NHL --date 2026-10-28 --max-games 5 --request-budget 20
```

Replace placeholders only with authentic provider game IDs from the actual eligible slate. Do not guess IDs. These are **read-only, bounded, aggregate-only** diagnostics. The join script fails closed on missing LAB/Sports credentials, no saved LAB player-prop rows, incomplete odds pagination, empty eligible odds, stale quotes, or no exact game/player/market/line match. LAB model signal age is separately bounded to 24 hours, while live sportsbook quote age is 15 minutes. An exact join is not evidence of a calibrated player hit probability; its output keeps betting and production approval false.

The private join script does not work from the credential-free public preview, and the connected Render integration cannot open a private shell. Do not copy provider secrets into chat, GitHub Actions, or a public Render service to work around that restriction. Preserve the existing production Render API/Worker and their credentials until the authorized acceptance process can be executed and audited.

Joint probability validation is **a distinct prospective task**: freeze model and joint-ticket versions before events, archive exact pregame market lines and independent sportsbook combined quotes, settle real outcomes, evaluate calibration (ECE/Brier/log loss and independent market baseline), and approve only the precise supported markets whose evidence passes. The present deployed status has zero prospective samples; therefore no joint wagering promotion is justified.

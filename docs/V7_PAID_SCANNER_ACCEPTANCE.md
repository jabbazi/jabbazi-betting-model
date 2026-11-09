# V7 paid-player scanner integration — draft / research-only

Owner scope override: November 1, 2026. This supersedes the older instruction in
Issue #79 that excluded comprehensive paid-player collection from Scan Everything.
This is implementation documentation, not evidence of production release.

## Existing architecture retained

Continue PR #80 through its nested PR #83 branch. Full `AutomaticScanner` runs now
invoke a separate NBA/NFL/NHL paid collection stage after ordinary team/market
research. Quick and moneyline-only runs do not invoke that stage. The existing
Odds API market/event caps, VIP authorization, scanner lease, immutable database,
Discord entitlements, and wager approval gates are retained.

The paid stage follows available game and prop pages, with exact sport isolation,
quote validation, deduplication, local monthly request accounting, rate pacing,
per-sport request allocation, socket/time/row limits, and explicit partial coverage.
It checks today's America/Chicago calendar, including the UTC rollover and DST.
The private runner also accepts tomorrow explicitly without replacing today's
snapshot. No automatic sportsbook execution or public publication is introduced.

## Data and model path

1. Existing BALLDONTLIE Sports API adapter collects all returned prop categories
   for discovered eligible games, not only the ordinary scanner's market sample.
2. Licensed quote rows are retained in private immutable `paid_player_quote_snapshot`
   events. Raw quotes are not returned by public routes or put into GitHub.
3. Existing, independently reviewed cross-provider identities are loaded from
   `paid_player_identity_manifest`. Provider game kickoff must still match.
4. Current event-scoped feature snapshots are selected from the existing store.
   Missing contexts may be refreshed through the existing real collectors, but
   only using a reviewed source name and canonical matchup. The exact source ID
   is checked again before model inference. There is no fuzzy-name auto-approval.
5. Existing versioned player distributions produce probabilities at the observed
   threshold. NHL count milestones N+ use P(X >= N), not P(X > N). Unsupported
   whole-line/push settlement, model families, features and markets remain unavailable.
6. LAB saved model signals are collected separately with their own credential.
   LAB confidence and scores are never substituted for calibrated hit probability.
   NHL LAB player props are unsupported; the NHL fitted model path is separate.
7. Genuine two-sided half-line O/U forecasts can be frozen in the existing
   `player_prospective_forecast` store with an exact same-book no-vig baseline.
   Single-sided milestones do not acquire a fabricated baseline. No results,
   wins, retrospective forecasts, or promotion approvals are generated.
8. Scan responses and the authenticated VIP view expose current model-only Top 10
   lists **per market**, separately from version-matched fitted stat averages.
   Freshness is rechecked when results are read. Refreshing a view is quota-free.

Missing identities, model artifacts, or verified features are rejection reasons,
not zero probabilities. A successful odds endpoint is not successful model inference.
`collection_complete`, `model_scope_complete`, and the combined `scope_complete`
are separate. No-games can complete a discovery scope but cannot pass live paid
endpoint acceptance. Partial paid research marks the ChatGPT scan PARTIAL without
erasing independent ordinary market research.

## Budget configuration

Defaults are deliberately bounded, not a promise of exhaustive coverage:

| Variable | Default | Meaning |
|---|---:|---|
| `JABBAZI_PAID_PLAYER_SCAN_ENABLED` | true | New owner-requested full-scan stage; false explicitly disables it |
| `JABBAZI_PAID_SCAN_REQUESTS` | 90 | Shared actual HTTP request maximum for Sports and LAB |
| `JABBAZI_PAID_SCAN_SECONDS` | 180 | Paid stage wall-time ceiling, also bounded by the parent scanner deadline |
| `JABBAZI_PAID_SCAN_MONTHLY_REQUESTS` | 12000 | Local monthly ceiling per provider family, not a claimed account balance |
| `JABBAZI_PAID_SCAN_MAX_GAMES` | 25 | Per-sport discovery cap; exceeding it does not silently truncate as FULL |
| `JABBAZI_PAID_SCAN_MAX_PROP_PAGES` | 25 | Per-game cap; unfinished cursors remain PARTIAL |
| `JABBAZI_PAID_SCAN_INTERVAL_SECONDS` | 13 | Conservative shared request spacing |

Faster pacing requires explicit `JABBAZI_PAID_SCAN_RATE_LIMIT_VERIFIED=true` plus
`JABBAZI_PAID_SCAN_VERIFIED_REQUESTS_PER_MINUTE`, and the configured interval must
respect that limit. Configuration does not prove subscription entitlement. At the
conservative default, a large slate will hit the time budget and report PARTIAL;
actual account limits must be independently verified before selecting faster
pacing. Existing global Odds API limits are not raised as a shortcut.

## Authorized private acceptance

The feature is not in the current production image. Use a reviewed isolated
checkout of the exact proposed commit in an already authorized runtime. Do not
merge/deploy unverified changes merely to gain access. Use existing secrets;
never paste provider keys, private identity manifests, or DB credentials into
GitHub or chat. Commands below are instructions, **not completed live evidence**.

Validate an already independently reviewed private manifest (no writes by default):

```sh
python -m tools.register_paid_identity_manifest --sport NBA --input /private/nba-identities.json
```

Only after real source review, explicitly register it:

```sh
python -m tools.register_paid_identity_manifest --sport NBA --input /private/nba-identities.json --commit-reviewed-manifest
```

Use NFL/NHL analogues with their actual source namespaces. Every mapping requires
provider player/game IDs, source identity and record checksum, canonical event ID,
matching kickoff, review timestamp, existing independent-review attestation and
matching record digest. `source_player_name` and `canonical_event_name` are needed
for a missing-context feature lookup. This tool does not add attestations or
prove real-world identity from a checksum.

Check configuration without API calls or database writes:

```sh
python -m tools.run_v7_paid_scan
```

Explicitly run the paid scan and private evidence capture:

```sh
python -m tools.run_v7_paid_scan --execute
python -m tools.run_v7_paid_scan --sport NHL --date YYYY-MM-DD --execute
```

The runner shares the scanner lease and budgets, emits aggregate counts/reasons,
and requires nonempty paid quotes for every requested sport before returning a
successful acceptance exit code. It never prints player records or secrets and
never promotes models or posts to Discord. Collect separate per-sport dates when
not all sports have eligible pregame games. Partial coverage is not acceptance.

## Separate release gates still required

- Current authenticated NBA/NFL/NHL endpoint coverage and exact-line model output
  from real reviewed identities and verified pregame snapshots.
- Independent chronological out-of-sample and prospective player-model validation.
- Genuine NBA/NHL joint-ticket calibration; a marginal model is not an SGP model.
- Authenticated executable combined sportsbook quotes, promotion/token eligibility,
  portfolio limits, and complete best-boost selection and delivery acceptance.
- Real VIP authorization/read flow and Discord channel/message receipts.
- Green final-commit CI, reviewed production release, deployment SHA verification
  on both existing Render services, and post-deployment checks.

No credential, role, network allowlist, production branch, or service configuration
change is authorized by this document. The source-audit/patch preparation workflow
used for development must not modify production refs or deploy any service.

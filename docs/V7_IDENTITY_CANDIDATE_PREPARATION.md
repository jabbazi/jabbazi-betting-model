# V7 identity-candidate preparation (development-only)

The reviewed-identity registration gate remains closed. No NBA/NFL/NHL
`paid_player_identity_manifest` records were present in the latest owner audit.

Tools `tools/prepare_goat_roster_candidates.py` and matching modules generate
**CANDIDATES_ONLY**, not independently verified crosswalks. They compare:
- NBA: BDL directory vs live ESPN roster, exact normalized name/team/jersey.
- NFL: BDL directory vs nflverse roster, exact name/team/jersey/position.
- NHL: BDL directory vs current official NHL roster, exact name/current-season
  team/position; NHL source does not assume jersey availability.

All use bounded existing provider adapters and fail closed on missing,
conflicting, duplicate or stale evidence. The NHL roster reads only official
public roster data. Private candidate rows stay in the authorized runtime,
with optional exclusive-create 0600 private export; stdout is deidentified.

**Candidate matches are not human-reviewed source identity proofs.** No tool
sets `independent_source_reviewed=true`, creates a manifest, enables
wagering, changes production credentials or deploys this PR. Run paid
collection only with a checked account budget, in an authorized isolated
runtime. Do not copy IDs/source rows to public PRs or chat.

Separate acceptance remains required for actual reviewed mappings, current
pregame model features, exact-line probabilities, calibration and releases.

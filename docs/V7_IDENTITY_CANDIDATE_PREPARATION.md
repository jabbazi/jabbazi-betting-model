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


## Private side-by-side candidate review

The candidate export is intentionally **not** an approved identity manifest.
For offline review in an authorized private runtime, each
`candidates_private[]` row now includes `review_evidence_private`: the
two observed player names, team, available position/jersey factors,
source observation time, and game kickoff. All are allowlisted, bounded
fields, paired with original provider/source record SHA-256 fingerprints.

The JSON file is created with exclusive-create mode `0600`; save it outside
the Git checkout, never commit it, never paste it into ChatGPT or CI logs,
and delete it using local approved retention procedures once reviewed.
A match on these visible factors remains **CANDIDATE_REQUIRES_INDEPENDENT_VERIFICATION**.
Reopen independently observed original source records before any privileged
registration; false positives and roster trades must be rejected.


## Official NHL roster URL correction (November 9, 2026)

Owner observed `/v1/roster/LAK/current` returning HTTP 307 with redirects
disabled, while `/v1/roster/LAK/20262027` returned HTTP 200 and a
15-forward / 7-defense / 2-goalie roster. The private NHL review adapter
now derives the explicit season path using the current season year:
July–December use YYYY/YYYY+1 and January–June use YYYY-1/YYYY.
This is roster-source retrieval only, **not** independent identity
attestation or current lineup availability. Off-season or outdated rosters
must still fail separate freshness and game-identity gates.

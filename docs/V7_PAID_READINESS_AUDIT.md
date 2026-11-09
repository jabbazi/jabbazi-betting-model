# V7 paid player readiness audit

The CLI `python -m tools.audit_v7_readiness` runs read-only in an **authorized
checkout containing the V7 code**. It does not run in the old production
image, invoke any paid provider, persist records, or register identities.

It reports per NBA/NFL/NHL: loadable model count, presence of any registered
identity-manifest version, 24-hour feature count, and source-gated verified
feature count, plus explicit non-approval reasons. A present manifest is **not**
proof its IDs are independently correct; a feature count is **not** proof it
belongs to the current quoted game/player/market. Even if all prerequisite
counts exist, the tool remains BLOCKED pending exact live-slate acceptance.

`NO_REGISTERED_REVIEWED_IDENTITY_MANIFEST` means the separately owned, private
source records still need independent review. No name/jersey/team similarity
can automatically produce an attestation. `NO_RECENT_VERIFIED_PLAYER_FEATURE_SNAPSHOTS`
means player-history research is not production-verified pregame evidence.
Source provenance for SportsDataIO is separately checked.

Run in an isolated authorized environment connected to the existing DB;
keep IP restrictions and production feature gating unchanged. A passing
pytest suite confirms report logic only, not successful live NBA/NFL/NHL
inference. The source query aggregates league-wide events, not individual
player records.

# Daily feed recovery, 2026-10-13

Scope: continue the existing production branch; no infrastructure or database
schema changes. Existing credentials, entitlements, frozen history, and model
approval gates remain intact.

## Changes

- Shared America/Chicago daily eligibility rejects undated, naive, inactive,
  started, and future-date events from pregame output.
- Apply eligibility to current VIP projections, parlay candidate selection,
  research/market observations, official-pick embeds, and daily sheet delivery.
  Recheck parlay and observation eligibility before sending.
- Preserve dates in parlay candidates. Old candidates without dates fail closed.
- Use approved logo assets in both sheet renderers, improve typography and fit,
  and prevent quarantined/validating models from supplying winner projections.
- Production acceptance version 4 checks actual board response date eligibility
  alongside existing sign-in, replay rejection, logout, and endpoint checks.

## Validation and limits

Full suite after final parlay preselection filter: 715 passed in 44.04 seconds
(one existing audioop deprecation warning). Ruff F checks and git diff whitespace checks passed.
Synthetic daily card visually inspected using the approved logo.
Local Chromium installation failed, so no claim of authenticated browser visual
acceptance is made. Production acceptance is transport/authentication evidence,
not model validation or proof of the complete Discord member command flow.

This patch does not approve any model, add first-TD training evidence, guarantee
provider availability, or validate all requested markets. Existing score-model
adapters cover NFL/CFB/NBA/MLB/NHL conditionally and return SHADOW_ONLY or an honest
unavailable state. No successful live simulation is claimed here.

Frozen rows can retain old status after provider rescheduling; final delivery
rechecks stored event times/status, not a new provider fetch. A comprehensive
live-status reconciliation and all-pipeline audit remain necessary. Historical
records remain accessible; daily pregame rows exclude games already underway.

## Deployment and rollback

Both services have automatic deployment disabled. Deploy API first, confirm
readiness, then worker so startup acceptance exercises the new API.
No migration is introduced. If regression occurs, revert this focused commit
and redeploy affected services. Previous observed live API commit:
739fe791600ed117673dc21feb5c4064c440eae8; worker:
64f4e29ac5acc2413087e1de35baa45eea0196b5.

Use PARTIALLY VERIFIED until required live and model evidence is complete.

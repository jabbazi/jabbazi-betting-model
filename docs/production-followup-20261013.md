# Production follow-up — 2026-10-13

Continues deployed 743948e without schema changes or changes to credentials,
roles, billing settings, historical snapshots, or model approval gates.

## Implemented

- Backend prop-family filtering before pagination; exact canonical market links.
- Match provider sport identifiers to the VIP workspace labels.
- Refresh daily views only on a Chicago date rollover, including responses that
  straddle midnight. Normal session polling does not refresh the active page.
- Compare queued deliveries with a healthy, complete provider scan at most 15
  minutes old. Missing events, changed starts, cancellation, and stale scans
  suppress delivery. Recheck after awaited work immediately before sending.
- Apply today-only filtering to legacy member sheets and images, active VIP
  projections, and private alert inboxes. Preserve historical records.
- Record successful official-pick issuance and require issuance evidence for
  official graphic exports; Play of the Day exports require its daily record.
- Add matchup start time, model status, snapshot timestamp, and bounded text.
- Extend production acceptance to NBA/NHL and server-filtered props. Add browser
  coverage for Chicago midnight, simulation lines, and first-TD unavailable state.

## Model evidence observed during this follow-up

Live model-status response: MLB/NFL/NHL/NBA game models SHADOW_ONLY, CFB
VALIDATING. Game adapters cover moneylines, spreads, totals, team totals and
alternate lines conditionally. Player-model buckets remain VALIDATING.
CFB player models are unavailable. No model was promoted.

SportsDataIO NFL CurrentSeason and MLB daily player projections both returned
HTTP_401. NHL/NBA fallback feature sources reported available. First-TD still
lacks an independently validated trained artifact and remains UNAVAILABLE.
The same-game engine remains RESEARCH_ONLY, with zero prospective joint-player
samples; independent leg multiplication is not validated same-game modeling.

## Remaining acceptance boundaries

Queued delivery checks the most recent saved provider observation, not a new
provider request at each send. Status changes after that observation remain a
source latency risk. The guard can suppress delivery when scans are stale; it
does not expand the provider-credit budget or increase the configured schedule.

Owner API acceptance does not prove every member's Discord DM flow. Billing-role
synchronization previously reported UNCONFIGURED; do not repurpose a manual or
Playbook-managed VIP role to silence that state. No production test posts are
needed for regression coverage; isolated SDK delivery tests use synthetic data.

## Deployment

Run the Python suite, lint, CI container checks and browser scenarios. Deploy API
before worker; inspect version-5 startup acceptance and both deployed SHAs.
Rollback is a focused revert and redeploy; no data migration is required.
Use PARTIALLY VERIFIED until member flows, model input availability, and required
validation evidence are complete.

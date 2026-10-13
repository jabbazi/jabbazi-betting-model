# Operations and research usability follow-up — October 13, 2026

Continues production 4fe9192. No schema change, data purchase, model promotion,
ledger mutation, permission expansion, or synthetic Discord publication.

## Implemented

- Owner-only health evidence within the existing admin panel: API commit,
  successful database reads, process-local pool occupancy, saved worker heartbeat,
  latest scan health and most recent success within 20 records, and recorded owner
  authentication acceptance. Future/malformed/old timestamps never count as fresh.
- Raw provider errors and arbitrary stored payload fields are excluded. Missing
  auth/queue/global database metrics are explicitly unmeasured. Reading this
  panel performs no provider calls and does not approve models.
- Sport workspaces retain successful sections when another section fails.
- Resource-only 403 errors no longer discard a valid member UI session; revoked
  VIP access and 401 still lock the interface.
- Research cards explain stale snapshots, unhealthy feeds, quarantined models,
  missing exact-line estimates, and models under evaluation, from existing facts.
- Game-page props preserve exact event identity through server filtering and
  pagination, including separate doubleheaders. Today links to the existing
  authentic performance view; its provenance and incomplete-coverage caveats remain.
- Daily performance now separates placed/unsettled stakes from settled ROI, shows actual settled stakes and returns, and retains push/void counts separately in the API. Reservations and member plays are excluded.
- Production acceptance v6 checks owner health availability in addition to v5 checks.

## Verification and limitations

Focused API tests cover owner authorization, field redaction, heartbeat freshness,
missing records, and exact-event props. Browser scenarios cover partial metadata
outages and resource permission failures without session loss. CI runs desktop and
mobile checks; production acceptance checks API transport, not predictive accuracy.

Existing role-based Discord alert choices remain intact. Per-member Discord quiet
hours and category delivery require a dedicated recipient delivery implementation;
this release does not pretend existing channel posts honor individual quiet hours.
Automated daily recap delivery is not added; the ledger-backed performance view and
graphic already exist. Verified live/member login, provider access, first-TD training,
and production model approval remain separate requirements.

Rollback: redeploy prior commit 4fe9192 on affected services. No migration rollback
is needed. Deployment and live verification must be checked separately from this file.

## Live correction

Initial v6 acceptance caught a 12-second Operations timeout. Health queries were
changed to extract only summary JSON fields in SQL, avoiding transfer of large
scan coverage payloads. A regression forbids full-record loading for this path.
The live acceptance check must pass after redeployment.

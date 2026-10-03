# Verified cloud rollout — September 25, 2026

This supersedes the **not deployed** status in the earlier reliability build report. It does not change model approval or validation conclusions.

## Release

- PR #5 merged into `build/production-foundations`.
- Deployed identical commit `333e5b7faa4afe7d9bdb07dc5243ebf105cde8cc` to both existing Render services.
- [API deployment](https://dashboard.render.com/web/srv-dapfgeff3r2c73citeog/deploys/dep-dar0dc0u01pc73bjpm7g): **Deploy succeeded / Live**, 45.9 seconds.
- [Worker deployment](https://dashboard.render.com/worker/srv-dapfub1srm7s73fbo7cg/deploys/dep-dar0du7avr4c73f9utq0): **Deploy succeeded / Live**, 45.4 seconds.
- Previous API revision: `d333e9c5a394051b47d159835bc499fbe36a1322`; previous worker revision: `16c17c0d1757639f577f7cf0cc04cd2ea65d5ddc`. Preserve these as rollback references.
- Existing OAuth and member-app source was checked against the previously deployed revision before rollout. No new service, plan upgrade or paid data purchase was made.

## Live checks

- `/healthz`: HTTP 200.
- `/readyz`: HTTP 200; database ready; betting disabled.
- Existing authenticated ChatGPT `get_model_status` works and returns per-market stages, with no errors.
- NFL: `nfl-score-ridge-0.1.0-8b55af293d53`, SHADOW_ONLY.
- MLB: `mlb-score-ridge-0.1.0-792a7fe3fb48`, SHADOW_ONLY.
- CFB: `cfb-recency-ridge-0.2.0-02fb8f011cd5-2026-01`, SHADOW_ONLY, seven team-market categories, no player props.
- Database migration log: platform schema version 1 ready.
- Worker heartbeat at `2026-09-25T05:32:24.678046+00:00`: RUNNING, closing collector HEALTHY, no closing errors, existing Discord process RUNNING, betting disabled.
- A startup heartbeat reported RuntimeError while the owner verification scan was active. Scanner lease contention is consistent with the code path and overlap; the precise exception message was not logged. Subsequent heartbeats recovered. No claim is made that the skipped scheduled scan itself completed.

## End-to-end scan

One bounded verification scan was requested with the existing 15-credit maximum and no publishing/wagering action:

- ID: `d22b6ee3-b666-48bc-a063-7e78a7492eab`.
- Started: `2026-09-25T05:31:05.813137+00:00`.
- Generated: `2026-09-25T05:32:35.241734+00:00` (12:32 a.m. Central).
- Status: COMPLETE; errors: none.
- Five feeds; 4,478 archived quotes; 1,432 candidate rows evaluated.
- 744 modeled candidates; 688 unmodeled candidates. No claim of complete market coverage.
- All 11 returned pages inspected: 260 retained rows, comprising 117 NFL, 88 CFB and 55 MLB rows. The API explicitly reports truncation; these are not all 1,432 candidates.
- Every returned row had zero stake and `model_can_influence_cash=false`.
- Reliability fields, provenance, shared score summaries, per-market SHADOW_ONLY stages, disagreement states and retrieval-time stale-price handling were present.
- Chiefs/Miami moneyline remained 49.814% for Miami versus 15.680% market probability, visibly EXTREME_DISAGREEMENT. The opposite side and Chiefs -10.5 were also flagged. Retained prices were stale at retrieval and returned PASS; this is not a current betting card.
- Existing MCP names/request shapes and scan polling/pagination continue working.

Full structured receipt: [deployment-verification.json](experiments/reliability-upgrade/deployment-verification.json).

## Remaining limitations

All calibration/promotion, personnel-feed, historical-price and player-prop limitations from [RELIABILITY_UPGRADE_REPORT.md](RELIABILITY_UPGRADE_REPORT.md) still apply. Deployment is not proof of an edge. CFB has a current bundled snapshot but ongoing refresh still needs a configured CFBD credential; no credential was added during this rollout. NFL/MLB refresh returned NOT_DUE in the startup heartbeat.

No manual Discord post, wager, bankroll change, new paid service or data purchase was performed. Existing configured background behavior was preserved. The immediate next work is prospective evaluation with real closing prices, verified personnel/context inputs, and distribution-level calibration.

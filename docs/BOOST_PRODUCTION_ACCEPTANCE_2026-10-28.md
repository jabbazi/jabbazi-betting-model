# V6 boost acceptance audit — 2026-10-28

## Release status

PARTIAL / RESEARCH ONLY. PR #80 remains draft and unmerged. This is not production acceptance.

The existing broad scanner, VIP entitlements, Discord permissions, production infrastructure, database network policy and secrets are preserved. No new provider subscription or model promotion is authorized by this report.

## Observed starting state

- PR #80 head before this review: aa07ca398f002d01769994939a710066e34eaed9.
- GitHub Actions run 40622175807 succeeded: tests/lint/API smoke, container/PostgreSQL/restore/outage checks, and VIP browser scenarios. This confirms the earlier authentication-test correction; these are not live provider or live Discord acceptance tests.
- Render API live deployment: dep-dbggm3a9lscs73f47k7g.
- Render worker live deployment: dep-dbggm3t9el5s738ejib0.
- Both deployment records identify production commit 8ede9800b85ff5073db95de731d8d9a26b978e53.
- NBA points and NHL goals artifacts are VALIDATING, promotion_passed=false, with no archived market-line calibration test samples.
- NFL joint-player model is a two-leg research checkerboard copula. Its artifact is explicitly not approved; prospective SGP validation is not completed.
- NBA joint module is an aligned single-player outcome contract, explicitly not a fitted/approved model. No NHL joint model was found in the inspected model tree.
- Boost API implements an owner-authenticated feed diagnostic, not an optimized recommendation workflow.
- Candidate selection ranks supplied exact offers; it does not generate sportsbook tickets or obtain validated joint probabilities.
- The existing promo API is hypothetical owner-only arithmetic. It does not approve wagers.
- NBA/NFL provider capture remains a bounded sample, not exhaustive eligible-slate retrieval. No successful live NHL prop probe was established in this session.

## Fixes implemented in this review

1. Model matching requires artifact promotion evidence in addition to a production-stage label.
2. Estimate model version must exactly match the registry version; missing versions and malformed integrity snapshots fail closed.
3. Joint audit rejects event overlap between test/prospective partitions, conflicting ticket outcomes across model versions, and blank provenance.
4. Boost play-to pricing now inverts the capped payout function and includes promotion minimum odds.
5. Regression tests cover each correction. Use the full Actions workflow for the final PR head; intermediate successful runs do not validate later commits.

The audit corrections prevent known evidence contamination; they do not prove a supplied test split was trained chronologically. Genuine training provenance, independent event separation, market baselines, calibrated uncertainty and prospective outcomes are still required. No synthetic calibration evidence was added.

## Blocking access and evidence

The execution tool returned: "No usable execution environment is available." GitHub file updates and Actions remain available, so reviewable corrections were committed remotely.

The read-only Render PostgreSQL connector returned that the database blocks all external connections because its IP allowlist is empty. Its hosted MCP server has no fixed addresses to allowlist. Do not open the database to the internet to bypass this boundary.

Required execution surface: a coding/runtime environment with this repository checked out and authorized private-network access to the existing Render service/database. Keep JABBAZI_BALLDONTLIE_API_KEY in the existing service secret environment. Do not copy its value into documentation, CI logs or chat. This session cannot execute an authenticated provider request inside Render or access its environment secrets.

## Remaining acceptance work

- Live authenticated NBA/NFL/NHL paid prop probes, including current game IDs and observation times.
- Normalize and deduplicate complete eligible-game pagination; audit scope, missing identities, removed/stale markets, quota/rate-limit handling and all eligible-market counts.
- Join paid feed event/player identities to the existing feature/model registries with timestamp/version provenance.
- Fit/evaluate NBA/NHL dependence using genuine historical aligned forecasts/outcomes, chronological partitions, calibration and market baselines. Retain research-only status until prospective approval qualifies.
- Enumerate permitted 2/3/4-leg structures and acquire exact sportsbook combined quotes. Never multiply correlated marginal probabilities or leg prices to invent SGP probability/price.
- Enforce full promotion terms, token/expiration, freshness, uncertainty and portfolio limits. Report PASS if any required evidence is unavailable.
- Connect the dedicated workflow to existing VIP and Discord surfaces with entitlement checks and integration tests; preserve Scan Everything isolation.
- Use 1u=$50 for this boost workflow, subject to stake caps and risk settings. No stake is recommended by this audit.
- Run full CI on the final head, staging acceptance, then merge/deploy only if safe and verify production health, provider counts, VIP/Discord, boost workflow and broad-scan regressions.

No production deployment, current full-slate coverage count, BET NOW recommendation or production-readiness claim is made by this document.

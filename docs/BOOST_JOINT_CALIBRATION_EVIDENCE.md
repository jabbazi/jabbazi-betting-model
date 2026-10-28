# V6 NBA/NHL joint calibration — evidence contract

**Status: research-only; no model promotion.** Existing `boost_joint_audit.py`
provides a lightweight descriptive audit. The stricter
`boost_joint_evidence.py` and `tools/audit_boost_joint_evidence.py` validate
whether a genuine archived joint-ticket dataset is eligible for expert review.
They do NOT fit a model or produce actionable SGP probabilities.

## What the local input must contain

Store each resolved exact-ticket prediction as one JSON object per line in a
PRIVATE UTF-8 JSONL file. Every entry requires:

- `sport`: `basketball_nba` or `icehockey_nhl`; `event_id`, `ticket_id`,
  and `model_version`: stable nonempty identities tied to the original archived
  event, **exact legs**, and frozen model revision.
- `split`: `test` or `prospective`; `trained_through`, `test_start`,
  `prospective_start`: fixed chronology for the model version.
- `probability`: the original **frozen joint ticket probability**, never a
  product reconstructed afterward from leg marginals; `outcome` is the
  authoritative final binary settlement (0 or 1), excluding pushes, voids and
  canceled tickets from the input with a separately auditable exclusion log.
- `market_probability` and `market_baseline_kind` with exact value
  `independently_quoted_combined_ticket`: an **independently observed,
  same-ticket combined market benchmark** with defensible no-vig normalization.
  If only a single quoted side or synthetic marginal product exists, this
  market baseline is NOT established. Do not relabel independent leg
  multiplication as a bookmaker SGP quote.
- `predicted_at`, `forecast_frozen_at`, `starts_at`,
  `features_available_at`, `market_observed_at`, and
  `result_observed_at`: timezone-aware event and evidence timestamps.
  Feature availability must precede prediction, prediction must precede
  archival freeze, and freeze precedes kickoff; settlement follows kickoff.
  Quoted benchmarks must precede prediction by no more than 600 seconds.
- `forecast_snapshot_sha256`, `result_snapshot_sha256`,
  `market_snapshot_sha256`: SHA256 digests of the *actual archived source
  evidence* under owner custody. Their presence is necessary but NOT proof
  that any source is authentic, chronologically frozen or independently
  witnessed. A separate owner audit must confirm the underlying immutable
  events and storage.

No example/fake evidence files are provided. Unit fixtures are deliberately
synthetic and MUST NEVER enter the research archive or promotion process.

## Run from a private authorized environment

```bash
python -m tools.audit_boost_joint_evidence --input /private/nba-nhl-exact-ticket-evidence.jsonl
```

The command does not need BALLDONTLIE credentials or network connectivity.
It performs no deploys, sends no Discord alerts, and writes no artifacts.
Output is a non-identifying metrics-only JSON report with input SHA256 and
`approved_for_betting=false`. An exit code of 0 indicates sufficient declared
evidence *for independent human/professional review*, never model approval.
1 indicates a missing sport, test or prospective partition or fewer than 200
independent events. 2 indicates an invalid or inaccessible input file.

## Validation and remaining work

- Each NBA/NHL model/version requires at least 200 **independent games in each
  test and prospective split** as a configurable minimum, not 200 correlated
  tickets from the same game. Audit uses per-game weights for Brier/log loss
  and compares to the exact independent combined-market benchmark.
- Enforce disjoint event sets across test and prospective, fixed training
  cutoff for the same model version, point-in-time feature and price
  availability, and consistent resolved ticket outcomes.
- Manual review must additionally examine the real source snapshots,
  selection bias, calibration by probability bucket, confidence intervals,
  sample-independent event clustering, closing-line evidence, lineup/goalie
  availability and stability across seasons. A positive Brier difference by
  itself is **not** sufficient for approval.
- Existing live model status has NBA/NHL player models `VALIDATING` and
  zero recorded prospective validation samples, so no currently observed
  records satisfy these approval requirements.
- If exact-ticket combined pregame quotes or frozen forecasts were never
  captured, the missing historical evidence cannot be reconstructed
  reliably from a present-day odds API. Start prospective archiving within
  the existing private database/infrastructure, preserve its network policy,
  and accumulate genuine resolved evidence over time.

Promotion, branch merge, Render deployment, production betting advice and
Discord publication are forbidden until the other independent gates in
`docs/BOOST_V6_RELEASE_GATE.md` pass. `SCAN EVERYTHING` is unchanged.

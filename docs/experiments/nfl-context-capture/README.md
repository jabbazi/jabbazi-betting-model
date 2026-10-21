# NFL source capture — September 23, 2026

The bounded capture succeeded on `076d1a38d621ddf48ed2168541d22476680de969`:
[run 35924197502](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35924197502).
It downloaded the fixed nflverse assets in `request.json` and an immutable schedule
revision. Exact source hashes, actual observation times and normalized snapshots
are retained in the run artifacts.

| Season | Source play rows | Completed games imported |
|---|---:|---:|
| 2021 | 49,922 | 285 |
| 2022 | 49,434 | 284 |
| 2023 | 49,665 | 285 |
| 2024 | 49,492 | 285 |
| 2025 | 48,771 | 285 |
| 2026 to capture | 5,489 | 32 |
| Total | 252,773 | 1,456 |

All selected games passed team/final-score reconciliation within the provider
data, not against an independent source. The importer produced **2,912 team-game
snapshots**. All **16 upcoming events** in the captured seven-day schedule window
had sufficient prior-game efficiency history under the current feature policy.
These are input counts, not predictions or proof of complete league coverage.

## Availability and model limitations

The capture was `2026-09-23T21:43:55.863398+00:00`. Downloading old games today does
not establish their original availability. Strict historical training-readiness
is therefore **zero**. Retrospective reconstruction would need a separate protocol
and could not be presented as an original receipt-time backtest. Upstream EPA
model training vintages also remain unverified for historical evaluation.

Schema `advanced-context-0.2.0` accepts either an actual `ended_at` or conservative
`completed_by`, never both. This capture uses observation of a reconciled final
score as its completion bound, without inventing exact end times. Lookbacks use
actual starts, so old games captured today do not become recent. Version 0.1.0
manifests remain accepted.

No advanced model was fitted or deployed, and no scanner probabilities or betting
approval changed. QB/injury/weather context, opponent adjustment and prop usage
distributions remain absent. Captured 2026 inputs are not an admitted new training
set or untouched holdout. Existing live model artifacts remain shadow-only.

## Reproduce and retain

```bash
PYTHONPATH=src python tools/capture_nfl_context.py \
  --request docs/experiments/nfl-context-capture/request.json \
  --output /new/output/directory
```

The output directory must be new. Changed source bytes fail the frozen digest
check; new revisions require a new request and receipt. The workflow runs only on
its request-file change or manual dispatch. No continuous collector was enabled.

`run-evidence.json` contains summaries from successful job logs and artifact API
metadata/digests. ZIP contents were not downloaded into the local workspace:
the download endpoint returned HTTP 403. The Actions job created and uploaded
both source and normalized files. Artifacts expire **December 22, 2026**; export
raw archives and receipts before then. Ninety-day retention is not durable audit
storage. Raw sources are about 100 MB; normalized/report output is about 144 KB.

Play-by-play data: **nflverse contributors, CC BY 4.0**. Aggregation: JABBAZI.
[License](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md).
[Corrections schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html).
This attribution does not establish rights for other feeds or third-party assets.
No provider key, purchase or new login was needed for this capture.

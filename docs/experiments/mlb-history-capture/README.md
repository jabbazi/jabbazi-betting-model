# MLB historical pitching capture — September 23, 2026

The information used here was obtained free of charge from and is copyrighted by
Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark,
DE 19711.

The bounded capture succeeded on `21a791d27dee3e68720f752bb51cb39846d04b08`:
[run 35925101387](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35925101387).
It preserved five original season ZIPs and the publisher's source/terms page,
recorded hashes and actual receipt times, and staged pitching CSV value rows.

| Season | Pitching appearances | Games | Actual starts |
|---|---:|---:|---:|
| 2021 | 21,964 | 2,467 | 4,934 |
| 2022 | 21,279 | 2,471 | 4,942 |
| 2023 | 21,062 | 2,472 | 4,944 |
| 2024 | 21,164 | 2,473 | 4,946 |
| 2025 | 21,368 | 2,478 | 4,956 |
| Total | 106,837 | 12,361 | 24,722 |

All selected numeric fields were populated. Counts include regular-season,
All-Star and postseason games, not an eligible training sample. Game types remain
available for explicit filtering. Actual starter flags describe completed games,
not what was confirmed before them.

## Missing evidence

- Original pregame starter/lineup announcements and subsequent revisions.
- Pitch-count workload, absent from this schema. Missing counts must not become
  zero; the current complete MLB feature vector is unavailable from these files.
- Verified Retrosheet-to-live-MLB/odds ID crosswalks, including doubleheaders and
  suspended games, plus true start/completion times.
- Current 2026 player logs, weather/lineup/bullpen observations and timestamped
  offered/closing prices for an execution backtest.

Rows are `STAGING_NOT_MODEL_INPUT`. Dates stay dates; the importer does not invent
timezones or historical observation times. Duplicate identities, malformed dates
and negative counts are rejected. It does not fit a model, produce prop
probabilities, change the live scanner or approve betting.

## Reproduce and retain

```bash
PYTHONPATH=src:. python tools/capture_mlb_history.py \
  --request docs/experiments/mlb-history-capture/request.json \
  --output /new/output/directory
```

The new directory contains `pitching-staging.jsonl.gz`, reports, request, receipts
and originals. ZIP members are read without extracting paths. Download and CSV
sizes are bounded. Official/lower/upper statistic variants cannot become duplicate
appearances. The workflow is bounded/manual, not a daily collector.

`run-evidence.json` preserves actual job-log summaries and artifact metadata with
ZIP digests. Output bytes remain in Actions artifacts; they were not locally
downloaded or independently replayed. Artifacts expire **December 22, 2026**;
export before then for durable reproducibility. Raw archives are about 50 MB;
normalized/report output is about 1.6 MB.

[Downloads and reuse notice](https://www.retrosheet.org/downloads/csvdownloads.html)
permits reuse with the prominent attribution above. The full notice is preserved
as `RETROSHEET-SOURCE-AND-TERMS.html` in both artifacts.
[Field definitions](https://www.retrosheet.org/downloads/csvcontents.html).
No paid data, credentials, provider sales contact or new login was used.

# Verification evidence — 2026-09-25

- Full local suite: **325 passed**, 9.75 seconds, one upstream discord.py/audioop deprecation warning.
- Ruff undefined/unused-name checks: passed.
- `git diff --check`: passed.
- Actual local HTTP smoke: passed. Liveness/readiness 200; unauthenticated request 401;
  authenticated DB read 200; absent odds provider 503; betting disabled.
- Exact Miami reproduction: passed, including 232/285 at +10.5 and 134/269 conditional ML.
- Original V4.2 source failed compilation with `unexpected character after line continuation character`, line 1.
  The repaired imported service module is tested in the scanner path.
- NFL rolling evaluation: 6 monthly folds, 284 decisive ML games (285 total games).
- MLB rolling evaluation: 9 monthly folds, 2,473 games.
- CFB rolling evaluation: 6 monthly folds, 800 FBS-v-FBS games.

Local SQLite is verified. PostgreSQL/container/backup-restore verification is delegated to
this repository's existing GitHub Actions jobs; their final status is recorded in the PR.
No production deployment occurred. Render is signed out in this workspace.

# Verification evidence — 2026-09-25

**Subsequent verification:** final-head CI passed **340 tests**, including PostgreSQL, and both services were deployed successfully. See [DEPLOYMENT_VERIFICATION_2026-09-25.md](DEPLOYMENT_VERIFICATION_2026-09-25.md) for live scan and health evidence. Earlier not-deployed statements below describe the build-time check.

- Full local suite: **326 passed**, 9.85 seconds, one upstream discord.py/audioop deprecation warning.
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

GitHub CI at commit `90dc8aa` passed **339 tests** (including 14 PostgreSQL tests),
Ruff, HTTP smoke, Docker build, API/worker stack, backup/restore and database-outage checks.
Both the [push run](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/36097679168)
and [PR run](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/36097935497) passed.
The subsequent report-provenance regression adds one test; final-head CI status is recorded in
[PR #5](https://github.com/jabbazi/jabbazi-betting-model/pull/5).
No production deployment occurred. Render is signed out in this workspace.

# Repository handoff

The target is `jabbazi/jabbazi-betting-model`, branch `build/production-foundations`.
Earlier attempts returned **403 Resource not accessible by integration** because
the connector was authorized but not installed on the GitHub account. Installation
restored write access on September 22, 2026, verified by creating the review branch.
The remote already contained a README; its main-branch history is preserved.

The downloadable handoff contains the reviewed source tree and `jabbazi-source.bundle`,
a portable Git bundle containing the local commit. Restore it with:

```bash
git clone jabbazi-source.bundle jabbazi-betting-model
cd jabbazi-betting-model
git remote remove origin
git remote add origin https://github.com/jabbazi/jabbazi-betting-model.git
```

The implementation is published in [draft PR #1](https://github.com/jabbazi/jabbazi-betting-model/pull/1).
All 94 files were compared with the fetched remote; their contents matched.
The portable bundle captures the earlier local checkpoint and does not replace
newer remote history. [CI run 35782687953](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35782687953)
passed 111 tests, Ruff, HTTP smoke, Docker build and the container CLI check for
commit `63775af158e6e8d688eefed6488a1f14fc292f37`. The PR remains unmerged.
Live deployment and model validation are separate outstanding milestones. Inspect
`docs/IMPLEMENTATION_STATUS.md` for the detailed review body and limitations.

The source archive omits credentials, raw provider data, live ledgers and trained
artifacts. The earlier saved starter still contains its original MLB/NFL research
artifacts and data snapshots. Their shadow status remains unchanged.

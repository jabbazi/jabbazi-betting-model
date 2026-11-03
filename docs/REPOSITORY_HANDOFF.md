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
The initial 94-file tree and the subsequent cloud/operations implementation were
compared with the fetched remote; their contents matched.
The portable bundle captures the earlier local checkpoint and does not replace
newer remote history. [CI run 35784881693](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35784881693)
passed 127 tests, Ruff, HTTP smoke, Docker build, PostgreSQL/API/worker integration,
disposable backup/restore and database-outage checks for source commit
`8f4e623c1a238a8a61aa3aefe28e94ddb03da987`. The PR remains unmerged.
Live deployment and model validation are separate outstanding milestones. Inspect
`docs/GO_LIVE.md` for hosting review and `docs/IMPLEMENTATION_STATUS.md` for the
detailed review body and limitations. GitHub is the current source of truth;
the downloadable source bundle is an earlier checkpoint, not the latest build.

The source archive omits credentials, raw provider data, live ledgers and trained
artifacts. The earlier saved starter still contains its original MLB/NFL research
artifacts and data snapshots. Their shadow status remains unchanged.

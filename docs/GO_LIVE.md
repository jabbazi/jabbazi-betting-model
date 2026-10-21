# JABBAZI cloud launch checklist

The research implementation is on [draft PR #1](https://github.com/jabbazi/jabbazi-betting-model/pull/1).
[CI](https://github.com/jabbazi/jabbazi-betting-model/actions/runs/35784881693)
passed 127 tests and the Docker/PostgreSQL API, worker, backup/restore and database
outage checks for that historical source revision. The later corrected API and
worker are now deployed on Render; see [live verification](CLOUD_VERIFICATION.md).
Provider authentication, Discord and production model approval remain unverified.

## 1. Review the prepared hosting resources

The repository contains a schema-validated `render.yaml`. Open the
[prepared Render deployment](https://render.com/deploy?repo=https://github.com/jabbazi/jabbazi-betting-model/tree/build/production-foundations)
and sign in securely. It uses the review branch, with automatic deploys disabled;
merging the PR is not required to inspect it. The owner completed signup and
provided a failed Blueprint-sync screenshot for commit `f7d4e0c`: worker creation
could not resolve the API's missing `JABAZI_BANKROLL`. API/database and billing
status were initially unverified. The missing configuration was subsequently
supplied and both services deployed successfully on commit `32c7f57`; the
[verification record](CLOUD_VERIFICATION.md) describes the checks and limits.
The recovery steps below are retained for future missing-setting incidents.

Estimated monthly baseline, checked September 22, 2026:

| Resource | Configuration | Estimate |
|---|---|---:|
| API | 0.5 CPU, 512 MB | $7.00 |
| Worker | 0.5 CPU, 512 MB | $7.00 |
| PostgreSQL | 0.1 CPU, 256 MB | $6.00 |
| Database storage | 5 GB at $0.30/GB | $1.50 |
| Total | Before taxes, usage overages and data providers | **$21.50/month** |

Estimates derive from [Render pricing](https://render.com/pricing) and its
[compute plans](https://render.com/docs/compute-plans). Confirm the actual account
quote and any workspace fees before creating resources. The user requires approval
before purchases. These small instances are a research starting point; production
capacity has not been load-tested. Services use Ohio; PostgreSQL external access
and storage autoscaling are disabled in the blueprint.

## 2. Configure private inputs

Use the host's secure environment configuration for an existing licensed Odds API
key and the actual bankroll. Do not paste secrets into chat or commit them.
The template generates the API bearer token and shares it and the database
connection with the worker. Enter the same reviewed bankroll and provider key
on both services; these manually supplied values are not cross-service references.
Set the monthly credit ceiling to fit
the account allowance; default 3000 is a ceiling, not a purchased plan. Provider
credits can be consumed once a configured worker starts. Leave Discord disabled.

Historical odds access requires a suitable paid provider plan. The historical
adapter and live collector exist; permitted redistribution, coverage and pricing
must be confirmed before a provider purchase. CFB's current training route also
requires `JABBAZI_CFBD_API_KEY`. No provider has been purchased.

## 3. Deploy and verify the real host

### Recover an existing Blueprint with a missing environment variable

The initial deployment could fail while creating the worker with
`environment variable not found: "JABAZI_BANKROLL" for jabbazi-research-api`.
The corrected template removes cross-service lookups for the manually supplied
bankroll and odds key. It does not invent or populate either value.

For an existing Blueprint, Render ignores new `sync: false` entries during sync;
it only prompts during initial creation. In each service's Environment settings,
set `JABAZI_BANKROLL` to the actual reviewed dollar amount and, when available,
set `JABAZI_ODDS_API_KEY` to the licensed provider key. Use identical values for
API and worker. If the worker does not yet exist, sync the corrected Blueprint
first to create it, then configure its Environment settings and redeploy it.
Production refuses to start without an explicit positive bankroll. An absent
odds key leaves the worker waiting without collection. Never paste keys into chat.
See [Render's secret-value rules](https://render.com/docs/blueprint-spec#prompting-for-secret-values).

Manual sync can create the previously failed paid worker. Review Render's resource
and billing summary before confirming; do not delete and recreate the database.

After resource/cost approval, the blueprint runs migrations, starts the API and
worker, and uses `/readyz` as the API health check. Verify real authenticated reads,
source timestamps, provider quota and worker/collector history. Use
[DEPLOYMENT.md](DEPLOYMENT.md) for commands and acceptance checks. Do not run the
synthetic CI ledger scripts on the real database. Configure restricted runtime
database permissions, external monitoring and a verified host backup/restore.

## 4. Connect the private Discord research room

An owner-controlled server and installed bot are required. The offline command
`python tools/discord_setup.py` prints the planned roles and channels. Its explicit
`--apply` option creates/updates them after checking the configured owner. Review
that output before applying it to an existing server.

Configure the bot token, guild, owner, analyst role, review channel and incoming
webhook in host secrets/settings. Check permissions with ordinary test accounts;
owners and administrators inherently bypass channel restrictions. Enable
`JABBAZI_DISCORD_REVIEW_ENABLED=true` only after those real checks. Test delivery
and inspect durable results before inviting members. Delivery can remain silent
when there is no qualified research candidate; no pick is forced for activity.

## 5. Complete model evidence before selling picks

MLB and NFL baselines remain `SHADOW_ONLY`; CFB has no real fitted artifact. The
NFL baseline underperformed its market diagnostic. Prop, touchdown, derivative
and parlay modules are research frameworks, not validated predictions. Trained
artifacts and provider data are intentionally absent from GitHub.

Acquire point-in-time features and prices, retain a new untouched evaluation
period, fit and calibrate each market separately, then track prospective results
and CLV with versioned evidence. Infrastructure tests do not establish profitability.
Paid memberships, payment processing and public paid alerts are not implemented.
The [implementation audit](IMPLEMENTATION_STATUS.md) lists each remaining scope.

# BALLDONTLIE research data connection

Set `JABBAZI_BALLDONTLIE_API_KEY` in the Render API and worker Environment settings.
Never put its value in this repository or a chat message. NBA and NFL subscription
access is separate. Existing Odds API and SportsDataIO credentials are unchanged.

On startup and every six hours, a background task acquires a shared database lease
and captures NBA/NFL games for today/tomorrow (America/Chicago), one 100-row page
of current-season player stats and injuries, and props for one returned game per
sport. This is a bounded access/ingestion sample, **not full-slate coverage**.
Requests are spaced 13 seconds apart; 429 stops the run. No subscription is bought
or upgraded. Pagination truncation, empty responses and endpoint errors remain
visible. NBA props use v2; NFL props use v1. Provider IDs are never assumed to
match ESPN, nflverse or Odds API IDs.

Data lives in `balldontlie_snapshot` records, with query, observed-at timestamp,
source checksum and raw payload. `balldontlie_status` contains safe summaries.
Owner-authenticated read endpoints:

- `GET /v1/providers/balldontlie`
- `GET /v1/providers/balldontlie/snapshots?sport=nba&resource=stats`
  (`sport`: nba/nfl; `resource`: games/stats/injuries/props)

The normal model-status response includes `player_feature_provider.balldontlie`.
Startup logs show only configuration presence, endpoint status and row counts.
HTTP 401 can indicate credential or subscription access failure; an HTTP 200 with
zero rows proves endpoint access, not useful data availability.

Model probability inputs are NOT switched by this release. Before enabling those,
join player/game identities with dates and teams, backfill complete historical
pages, map feature definitions, enforce decision-time availability, and evaluate
out of sample. Current model approval states and stake limits remain unchanged.
Observed-at samples cannot be backdated into historical pregame evidence.

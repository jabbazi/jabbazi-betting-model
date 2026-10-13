# Pending-data completion work — October 13, 2026

Continues 00af98a; original branding, entitlement rules, data sources and validation
statuses are unchanged. No paid subscriptions or synthetic production messages.

- Add two latest-event lookup indexes in the predeploy migration. PostgreSQL uses
  CREATE INDEX CONCURRENTLY, a 60-second statement budget and 5-second lock budget.
  Validity is checked before deploy proceeds. This is additive and compatible with
  older code/schema version 1; no evidence or table data is rewritten. If creation
  fails, inspect any invalid new index rather than repeatedly retrying blindly.
  Optional rollback: DROP INDEX CONCURRENTLY for ix_platform_events_kind_latest
  and ix_platform_events_kind_entity_latest (not needed for application rollback).
- Keep home shell fast; load today's event links, issued official picks, research
  and ledger recap separately, with isolated error handling and midnight guards.
- Exact-game props and cheat sheet navigation plus issued-pick section in matchups.
  Injury/lineup context explicitly unavailable unless independently surfaced in
  research provenance; no guesses or blanket confirmed-lineup labels.
- Settings opt-in private Discord watchlist DMs: sport/category filters and Chicago
  quiet hours. Defaults remain off. Current VIP entitlement, preferences, watchlist
  membership, freshness and canonical event eligibility are checked before send.
  Five-minute expiry and durable claims prevent duplicate/stale replay. Suppressed
  quiet-hour alerts are consumed. Pre-send failures allow at most three attempts;
  ambiguous sends are not retried. Receipts retain SENT or FAILED_OR_UNKNOWN.
  Shared-channel posts and role-based /alerts choices are unaffected. Live DM
  recommendations are not supported by the existing pregame watchlist engine.
- Existing automated results lane remains enabled only by its existing channel
  configuration; delivery receipts now distinguish known success from ambiguity.
- Production acceptance v7 additionally checks /today and requires health query
  completion. Read-only owner checks are not real-member command verification.

Tests cover index idempotence, preference validation, opt-in and deduplication,
midnight/DST quiet hours, expired notifications, and fast home separation.
Real Discord delivery requires a member to opt in; no unsolicited test is sent.

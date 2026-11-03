# Platform schema version 1

Run `python -m jabazi.persistence.migrate` using the migration owner's credentials.
The executable migration lives in `jabazi.persistence.store.Store.migrate` and records
version 1 in `platform_schema_versions`. Repeated execution is safe; a newer schema
is rejected. Future changes need explicit numbered migration steps before deployment.

Tables: `platform_events` (immutable evidence), `platform_positions` (transactional
risk/lifecycle projection), `platform_leases` (worker exclusion), and schema versions.
Evidence includes raw payloads, quotes, decisions, reservations, transitions and scan
health. This is an event-oriented schema, not completion of every proposed entity.

The earlier unused PostgreSQL schema is preserved in
`docs/archive/legacy_schema_template.sql`. Do not run it as the current migration.

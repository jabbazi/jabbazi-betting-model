"""Additive latest-event indexes, built without blocking production writes."""
from sqlalchemy import text

INDEXES = {
    'ix_platform_events_kind_latest': '(kind, occurred_at DESC, id)',
    'ix_platform_events_kind_entity_latest': '(kind, entity, occurred_at DESC, id)',
}


def ensure_lookup_indexes(store):
    # Each definition is fixed code, never user input. Existing evidence is untouched.
    with store.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        postgres = conn.dialect.name == 'postgresql'
        if postgres:
            conn.execute(text("SET statement_timeout = '60s'"))
            conn.execute(text("SET lock_timeout = '5s'"))
        for name, columns in INDEXES.items():
            conn.execute(text(f"CREATE INDEX {'CONCURRENTLY ' if postgres else ''}IF NOT EXISTS {name} ON platform_events {columns}"))
            if postgres:
                valid = conn.execute(text('SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)'), {'name': name}).scalar()
                if valid is not True:
                    raise RuntimeError('Latest-event index is not valid; inspect deployment before retrying')
    return list(INDEXES)

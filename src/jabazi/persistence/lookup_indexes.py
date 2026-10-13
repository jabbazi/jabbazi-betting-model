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
            conn.execute(text("SET statement_timeout = '600s'"))
            conn.execute(text("SET lock_timeout = '5s'"))
        for name, columns in INDEXES.items():
            if postgres:
                existing = conn.execute(text("SELECT indisvalid, pg_get_indexdef(indexrelid) AS definition FROM pg_index WHERE indexrelid = to_regclass(:name)"), {'name': name}).mappings().first()
                if existing:
                    expected = f"CREATE INDEX {name} ON public.platform_events USING btree {columns}"
                    if existing['definition'] != expected:
                        raise RuntimeError('Existing lookup index definition differs; manual inspection required')
                    print(f"Lookup index {name} valid={existing['indisvalid']}", flush=True)
                    if not existing['indisvalid']:
                        # Recover only our exact additive index after an interrupted build.
                        conn.execute(text(f"DROP INDEX CONCURRENTLY {name}"))
                        print(f"Recovering interrupted lookup index {name}", flush=True)
            conn.execute(text(f"CREATE INDEX {'CONCURRENTLY ' if postgres else ''}IF NOT EXISTS {name} ON platform_events {columns}"))
            if postgres:
                valid = conn.execute(text('SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)'), {'name': name}).scalar()
                if valid is not True:
                    raise RuntimeError('Latest-event index is not valid; inspect deployment before retrying')
    return list(INDEXES)

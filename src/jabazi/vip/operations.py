"""Read-only, bounded operational evidence. Never fetch provider data here."""
from datetime import UTC, datetime
import os
import re

from sqlalchemy import select
from ..persistence.store import events

from .data import timestamp


def observed(record, now, max_age):
    if not record:
        return {'state': 'UNAVAILABLE', 'observed_at': None, 'age_seconds': None}
    at = timestamp(record['payload'].get('completed_at') or record['occurred_at'])
    age = (now-at).total_seconds() if at else None
    return {'state': 'CURRENT' if age is not None and 0 <= age <= max_age else 'STALE',
            'observed_at': at.isoformat() if at else None,
            'age_seconds': round(age) if age is not None and age >= 0 else None}



def summaries(store, kind, fields, limit=1, entity=None):
    # Scan payloads contain large coverage trees. Never transfer/decode those
    # trees just to display a heartbeat or the last successful scan timestamp.
    query = select(events.c.occurred_at, *((events.c.payload[key].as_boolean() if key == 'healthy' else events.c.payload[key]).label(key) for key in fields)).where(events.c.kind == kind)
    if entity:
        query = query.where(events.c.entity == entity)
    query = query.order_by(events.c.occurred_at.desc(), events.c.id).limit(limit)
    with store.engine.connect() as conn:
        return [{'occurred_at': row['occurred_at'], 'payload': {key: row[key] for key in fields}}
                for row in conn.execute(query).mappings()]


def health(store, now=None):
    now = now or datetime.now(UTC)
    heartbeats = summaries(store, 'worker_heartbeat', ('status', 'completed_at'), entity='research_worker')
    scans = summaries(store, 'scan_run', ('healthy', 'completed_at', 'errors'), limit=20)
    acceptances = summaries(store, 'vip_acceptance', ('status',), entity='terminal-v1')
    heartbeat = heartbeats[0] if heartbeats else None
    latest = scans[0] if scans else None
    successful = next((r for r in scans if r['payload'].get('healthy') is True), None)
    worker = observed(heartbeat, now, 180)
    worker['state'] = ('RUNNING' if heartbeat['payload'].get('status') == 'RUNNING' else 'DEGRADED') if worker['state'] == 'CURRENT' else worker['state']
    scan = observed(latest, now, 10800)
    if latest and scan['state'] == 'CURRENT' and latest['payload'].get('healthy') is not True:
        scan['state'] = 'DEGRADED'
    scan['error_count'] = len(latest['payload'].get('errors') or []) if latest else None
    scan['last_successful_at'] = observed(successful, now, 10800)['observed_at']
    scan['history_scope'] = 'Latest 20 recorded scans; missing success is not proof no earlier success exists.'
    pool = store.engine.pool
    pool_metrics = {key: getattr(pool, method)() for key, method in [('size', 'size'), ('checked_out', 'checkedout'), ('overflow', 'overflow')] if callable(getattr(pool, method, None))}
    commit = os.getenv('RENDER_GIT_COMMIT', '')
    commit = commit if re.fullmatch(r'[a-f0-9]{40}', commit) else None
    acceptance = acceptances[0] if acceptances else None
    return {'observed_at': now.isoformat(), 'api': {'state': 'RESPONDING', 'commit': commit},
            'database': {'state': 'READ_SUCCEEDED', 'pool': pool_metrics, 'scope': 'This API process only; not database-wide utilization.'},
            'worker': worker, 'scan': scan,
            'authentication_check': {**observed(acceptance, now, 86400),
                'passed': acceptance['payload'].get('status') == 'VERIFIED' if acceptance else None,
                'scope': 'Recorded owner API acceptance; does not verify real-member Discord handoff.'},
            'unavailable_metrics': ['Authentication failure counts', 'Discord delivery queue age and failure totals', 'Database-wide connection pressure'],
            'notice': 'Saved operational observations only. Healthy services do not approve models or wagers.'}

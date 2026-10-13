"""Read-only, bounded operational evidence. Never fetch provider data here."""
from datetime import UTC, datetime
import os
import re

from .data import timestamp


def observed(record, now, max_age):
    if not record:
        return {'state': 'UNAVAILABLE', 'observed_at': None, 'age_seconds': None}
    at = timestamp(record['payload'].get('completed_at') or record['occurred_at'])
    age = (now-at).total_seconds() if at else None
    return {'state': 'CURRENT' if age is not None and 0 <= age <= max_age else 'STALE',
            'observed_at': at.isoformat() if at else None,
            'age_seconds': round(age) if age is not None and age >= 0 else None}


def health(store, now=None):
    now = now or datetime.now(UTC)
    heartbeats = store.list_records('worker_heartbeat', 1, entity='research_worker')
    scans = store.list_records('scan_run', 20)
    acceptances = store.list_records('vip_acceptance', 1, entity='terminal-v1')
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

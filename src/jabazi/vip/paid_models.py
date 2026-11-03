"""Saved member research signals only; this release contains no paid LAB reader.

Existing persisted signals are explicitly not calibrated model hit probabilities.
No credentials, provider clients, collection jobs or model approval are involved.
"""
from datetime import UTC, datetime

SPORTS = {"NBA": "nba", "NFL": "nfl", "NHL": "nhl"}
LAB_PLAYER_PROP_SPORTS = frozenset({"NBA", "NFL"})


def saved_paid_player_models(store, sport, slate_date, *, offset=0, now=None):
    """Read allowlisted saved source signals; views never spend provider credits."""
    now = now or datetime.now(UTC)
    if sport not in SPORTS or not 0 <= offset <= 10000:
        raise ValueError('Invalid saved-research scope')
    report = {'provider': 'BALLDONTLIE_LAB', 'sport': sport,
              'slate_date': slate_date.isoformat(), 'state': 'UNAVAILABLE',
              'reason': 'NO_SAVED_LAB_SNAPSHOT', 'rows': [], 'total': 0, 'next': None,
              'coverage_complete': False, 'paid_requests_made': 0, 'betting_enabled': False,
              'model_hit_probabilities_verified': False,
              'notice': 'Saved LAB signals only. Scores and confidence are not hit probabilities. Opening this page makes no provider requests.'}
    if sport not in LAB_PLAYER_PROP_SPORTS:
        report['reason'] = 'LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED'
        return report
    records = store.list_records('paid_lab_signal_snapshot', 20, entity=sport)
    record = next((r for r in records if r.get('payload', {}).get('slate_date') == slate_date.isoformat()), None)
    if not record:
        return report
    payload = record['payload']
    from .data import age_ok
    report.update({k: payload.get(k) for k in ('state', 'reason', 'observed_at', 'models_found', 'models_checked', 'predictions_seen', 'coverage_complete')})
    allowed = {'id', 'sport', 'model_id', 'model_name', 'market', 'game_id', 'player_id',
               'player_name', 'starts_at', 'model_signal_value', 'predicted_side', 'market_line',
               'provider_confidence_raw', 'created_at', 'provenance'}
    rows = [{**{k: r.get(k) for k in allowed}, 'approval': 'RESEARCH_ONLY',
             'model_hit_probability': None, 'hit_probability_verified': False}
            for r in payload.get('rows', []) if isinstance(r, dict)]
    report.update(rows=rows[offset:offset+50], total=len(rows), next=offset+50 if offset+50 < len(rows) else None,
                  snapshot_id=record['id'], stale=not age_ok(payload.get('observed_at'), now, 3600))
    if report['stale']:
        report.update(state='STALE', reason='SAVED_LAB_SNAPSHOT_EXPIRED')
    return report

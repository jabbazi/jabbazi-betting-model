"""Member-owned preferences, watchlist state and deduplicated inbox events."""
from datetime import UTC, datetime
from sqlalchemy import select

from ..persistence.store import events, digest


def owner_key(principal):
    return str(principal['guild']) + ':' + str(principal['member'])


def read_state(store, kind, owner, default=None):
    rows = store.list_records(kind, 1, entity=owner)
    return rows[0]['payload'] if rows else (default or {})


def change_watch(store, owner, candidate, remove=False, threshold=None):
    with store.transaction() as conn:
        row = conn.execute(select(events.c.payload).where(events.c.kind == 'vip_watchlist', events.c.entity == owner).order_by(events.c.occurred_at.desc(), events.c.id).limit(1)).first()
        items = list((row[0] if row else {}).get('items', []))
        items = [w for w in items if w['id'] != candidate['id']]
        if not remove:
            if len(items) >= 100:
                raise ValueError('Watchlist is limited to 100 opportunities.')
            items.append({'id': candidate['id'], 'event': candidate['event'], 'selection': candidate['selection'], 'sport': candidate['sport'], 'threshold': threshold, 'added_at': datetime.now(UTC).isoformat()})
        value = {'items': items}
        store._append(conn, 'vip_watchlist', owner, value, digest(['vip_watchlist', owner, value, datetime.now(UTC).isoformat()]))
    return value


def check_watches(store, owner, board):
    items = read_state(store, 'vip_watchlist', owner).get('items', [])
    prefs = read_state(store, 'vip_preferences', owner)
    index = {r['id']: r for r in board['rows']}
    previous = read_state(store, 'vip_watch_state', owner).get('items', {})
    current = {}
    for w in items:
        r = index.get(w['id'])
        state = 'UNAVAILABLE' if not r else 'PRICE CHECK' if not r['fresh'] else r['status']
        if r and r['fresh'] and w.get('threshold'):
            state = 'PRICE TARGET MET' if r['decimal'] and r['decimal'] >= w['threshold'] else 'BELOW PRICE TARGET'
        current[w['id']] = {'state': state, 'price': r.get('decimal') if r else None}
        old = previous.get(w['id'])
        if old and old['state'] != state and prefs.get('notifications', True):
            key = digest(['vip_alert', owner, w['id'], board.get('snapshot_id'), old['state'], state])
            store.append('vip_notification', owner, {'id': w['id'], 'event': w['event'], 'selection': w['selection'], 'before': old['state'], 'state': state,
                                                   'price': r.get('decimal') if r else None, 'at': datetime.now(UTC).isoformat(),
                                                   'notice': 'Research alert, not betting approval.'}, key)
    if previous != current:
        store.append('vip_watch_state', owner, {'items': current}, digest(['watch_state', owner, current, datetime.now(UTC).isoformat()]))


def poll_watchlists(store):
    from .data import board
    snapshot = board(store)
    # Distinct owners only; payloads and preferences never enter public logs.
    with store.engine.connect() as conn:
        owners = conn.execute(select(events.c.entity).where(events.c.kind == 'vip_watchlist').distinct().limit(1000)).scalars().all()
    for owner in owners:
        check_watches(store, owner, snapshot)
    return {'owners_checked': len(owners), 'delivery': 'PRIVATE_IN_APP_INBOX'}

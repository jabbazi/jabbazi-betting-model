"""Bounded projections of canonical research, official decisions and frozen sheets."""
from datetime import UTC, datetime
import math
import re
from zoneinfo import ZoneInfo

from ..discord_daily import sport_label
from ..persistence.store import digest

SPORTS = ('MLB', 'NFL', 'CFB', 'NBA', 'NHL', 'WNBA', 'TENNIS', 'SOCCER')
ALIASES = {'kc': 'kansas city', 'chiefs': 'kansas city chiefs', 'nyy': 'new york yankees', 'ny yankees': 'new york yankees', 'hr': 'home runs', 'td': 'touchdowns', 'atd': 'anytime touchdowns', 'lsu': 'lsu', 'ml': 'h2h'}


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d if d.tzinfo else None
    except (TypeError, ValueError):
        return None


def age_ok(value, now, seconds):
    at = timestamp(value)
    return at is not None and 0 <= (now - at).total_seconds() <= seconds


def identity(r):
    return digest([str(r.get(k) or '') for k in ('sport', 'event_id', 'event', 'market', 'participant', 'selection', 'line')])[:32]


def normalize(text):
    words = re.sub(r'[^a-z0-9]+', ' ', str(text).lower()).split()
    return ' '.join(ALIASES.get(w, w) for w in words)


def allowed_market(r):
    # Configurable policy is administered server-side; LA remains the default.
    import os
    if sport_label(r.get('sport', '')) != 'CFB':
        return True
    if os.getenv('JABBAZI_APP_COLLEGE_PLAYER_MARKETS', 'false').lower() != 'true':
        return not (str(r.get('market', '')).startswith(('player_', 'batter_', 'pitcher_')) or (r.get('participant') and r.get('market') not in {'team_totals', 'alternate_team_totals'}))
    return True


def project(r, record, now, historical=False):
    if not allowed_market(r):
        return None
    label = sport_label(r.get('sport', ''))
    if label not in SPORTS:
        return None
    p = number(r.get('research_probability', r.get('model_probability')))
    p = p if p is not None and 0 < p < 1 and r.get('model_version') else None
    market_p = number(r.get('market_no_vig_probability'))
    market_p = market_p if market_p is not None and 0 < market_p < 1 else None
    price = number(r.get('decimal_odds'))
    price = price if price is not None and price > 1 else None
    start = timestamp(r.get('starts_at_utc'))
    invalidated = str(r.get('event_status', '')).lower() in {'cancelled', 'canceled', 'postponed', 'suspended'} or str(r.get('status', '')).upper() == 'INVALIDATED'
    fresh = bool(not invalidated and not historical and record['payload'].get('healthy') and age_ok(record['payload'].get('completed_at'), now, 10800)
                 and age_ok(r.get('price_time_utc'), now, 300) and start and start > now
                 and not r.get('price_stale') and r.get('executable') is True)
    status = str(r.get('status', 'WATCH')).replace('_', ' ')
    quarantined = status == 'QUARANTINED' or r.get('anomaly_state') in {'QUARANTINED', 'EXTREME_DISAGREEMENT'}
    state = 'INVALIDATED' if invalidated else 'QUARANTINED' if quarantined else 'PRICE CHECK' if not fresh else 'PASS' if status == 'PASS' else 'WATCH'
    uncertainty = number(r.get('uncertainty'))
    playto = number(r.get('maximum_playable_decimal'))
    books = []
    for book, quote in (r.get('book_prices') or {}).items():
        value = number(quote)
        if value and value > 1:
            books.append({'book': str(book), 'decimal': value})
    return {'id': identity(r), 'snapshot_id': record['id'], 'sport': label, 'event_id': r.get('event_id'),
            'event': str(r.get('event') or ''), 'player': r.get('participant'), 'market': r.get('market'),
            'selection': r.get('selection'), 'line': r.get('line'), 'book': r.get('book'), 'decimal': price,
            'model_probability': p, 'calibrated_probability': number(r.get('calibrated_model_probability')),
            'market_probability': market_p, 'fair_decimal': 1/p if p else None,
            'edge': p-market_p if p is not None and market_p is not None else None,
            'ev': p*price-1 if p and price else None, 'play_to_decimal': playto if playto and playto > 1 else None,
            'model_version': r.get('model_version'), 'model_stage': r.get('model_stage', 'UNAVAILABLE'),
            'uncertainty': uncertainty, 'uncertainty_kind': 'policy haircut, not a confidence interval',
            'status': state, 'fresh': fresh, 'historical': historical, 'lifecycle': 'INVALIDATED' if invalidated else 'HISTORICAL' if historical else 'EXPIRED' if start and start <= now else 'UPCOMING',
            'price_at': r.get('price_time_utc'), 'starts_at': r.get('starts_at_utc'), 'snapshot_at': record['payload'].get('completed_at', record['payload'].get('generated_at')),
            'data_health': r.get('data_health', 'UNKNOWN'), 'approved_for_betting': False,
            'why': 'Historical research snapshot; recheck current evidence.' if historical else 'Price requires a fresh check.' if not fresh else 'Research estimate compared with observed market consensus; not an official wager.',
            'risks': ['Model estimates may be experimental.', 'Lineup, injury and weather confirmation are not included unless explicitly sourced.'],
            'other_prices': sorted(books, key=lambda b: -b['decimal'])}


def board(store, *, now=None, record=None, historical=False):
    now = now or datetime.now(UTC)
    rows = store.list_records('research_sheet', 1, entity='latest_scan') if record is None else [record]
    if not rows:
        return {'state': 'UNAVAILABLE', 'rows': [], 'snapshot_id': None, 'snapshot_at': None}
    record = rows[0]
    output = [project(r, record, now, historical) for r in record['payload'].get('rows', [])[:10000]]
    controls = flags(store)
    for r in output:
        if r and (controls.get('pause_all') or controls.get('pause_' + r['sport'].lower())):
            r.update(status='QUARANTINED', fresh=False, why='Publishing paused by an administrator.')
    return {'state': 'HEALTHY' if record['payload'].get('healthy') and age_ok(record['payload'].get('completed_at'), now, 10800) else 'DEGRADED',
            'rows': list({r['id']: r for r in output if r}.values()), 'snapshot_id': record['id'], 'snapshot_at': record['payload'].get('completed_at'),
            'partial': bool(record['payload'].get('truncated')), 'server_time': now.isoformat()}


def preference(store, principal):
    rows = store.list_records('vip_preferences', 1, entity=principal['guild'] + ':' + principal['member'])
    return rows[0]['payload'] if rows else {'unit_size': 30, 'sports': [], 'books': [], 'teams': [], 'notifications': True, 'bankroll': None}


def flags(store):
    rows = store.list_records('vip_controls', 1, entity='global')
    return rows[0]['payload'].get('flags', {}) if rows else {}


def paused(store, sport):
    f = flags(store)
    return f.get('pause_all', False) or f.get('pause_' + str(sport).lower(), False)


def official(store, now=None):
    from ..discord_content import official_pick_embed
    now = now or datetime.now(UTC)
    output = []
    for row in store.list_records('candidate', 100):
        p = row['payload']
        label = sport_label(p.get('price', {}).get('sport', ''))
        if paused(store, label) or official_pick_embed(p, now=now) is None:
            continue
        price = p['price']
        item = project({'sport': price.get('sport'), 'event_id': price.get('event_id'), 'event': price.get('event'),
                        'market': price.get('market'), 'participant': price.get('participant'), 'selection': price.get('selection'), 'line': price.get('line'),
                        'book': price.get('best_book'), 'decimal_odds': price.get('best_decimal'), 'research_probability': p.get('model_probability'),
                        'market_no_vig_probability': price.get('consensus_probability'), 'model_version': p.get('model_version'),
                        'model_stage': p.get('reliability', {}).get('model_stage'), 'price_time_utc': price.get('source_timestamp'),
                        'starts_at_utc': price.get('starts_at'), 'maximum_playable_decimal': p.get('maximum_playable_decimal'),
                        'executable': True}, {'id': row['id'], 'payload': {'healthy': True, 'completed_at': now.isoformat()}}, now)
        if item:
            item.update(id=row['id'], status='BET NOW', approved_for_betting=True, why=str(p.get('reason') or 'Cleared shared cash-authority gates.')[:500])
            output.append(item)
    return output


def frozen(store, date=None):
    date = date or datetime.now(UTC).astimezone(ZoneInfo('America/Chicago')).date().isoformat()
    records = store.list_records('daily_moneyline_sheet', 1, entity=date)
    if not records:
        return {'state': 'UNAVAILABLE', 'date': date, 'rows': [], 'notice': 'The healthy 9 AM CT moneyline sheet has not been published for this date.'}
    record = records[0]
    rows = []
    for raw in record['payload']['rows']:
        value = project({**raw, 'market': 'h2h'}, record, datetime.now(UTC), historical=True)
        if value:
            rows.append(value)
    return {'state': 'FROZEN', 'version': '9 AM INITIAL', 'date': date, 'id': record['id'], 'generated_at': record['payload']['generated_at'], 'rows': rows}

"""Bounded projections of canonical research, official decisions and frozen sheets."""
from datetime import UTC, datetime
import math
import re
from zoneinfo import ZoneInfo

from ..discord_daily import sport_label
from ..daily_scope import eligible_today, reconciled_event
from ..persistence.store import digest

SPORTS = ('MLB', 'NFL', 'CFB', 'NBA', 'NHL', 'WNBA', 'TENNIS', 'SOCCER')
ALIASES = {'kc': 'kansas city', 'chiefs': 'kansas city chiefs', 'nyy': 'new york yankees', 'ny yankees': 'new york yankees', 'hr': 'home runs', 'td': 'touchdowns', 'atd': 'anytime touchdowns', 'lsu': 'lsu', 'ml': 'h2h'}


def number(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
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


def project(r, record, now, historical=False, slate_date=None):
    if not historical and not eligible_today(r, now=now, slate_date=slate_date):
        return None
    if not historical and 'slate_events' in record['payload'] and not reconciled_event(r, record['payload']['slate_events'], now=now, slate_date=slate_date):
        return None
    if not allowed_market(r):
        return None
    label = sport_label(r.get('sport', ''))
    if label not in SPORTS:
        return None
    p = number(r.get('research_probability') if r.get('research_probability') is not None else r.get('model_probability'))
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
    anomaly = str(r.get('anomaly_state') or '').upper()
    quarantined = status == 'QUARANTINED' or anomaly == 'QUARANTINED'
    safety_review = anomaly == 'EXTREME_DISAGREEMENT'
    state = 'INVALIDATED' if invalidated else 'QUARANTINED' if quarantined else 'SAFETY REVIEW' if safety_review else 'PRICE CHECK' if not fresh else 'PASS' if status == 'PASS' else 'WATCH'
    from .research import MODEL_STAGES, binary_market
    model_at = r.get('model_time_utc') or record['payload'].get('completed_at')
    model_fresh = bool(not historical and not invalidated and not quarantined and not safety_review
                       and start and start > now and r.get('data_health') == 'HEALTHY'
                       and age_ok(record['payload'].get('completed_at'), now, 10800)
                       and age_ok(model_at, now, 10800)
                       and (not r.get('features_available_at') or age_ok(r['features_available_at'], now, 3600))
                       and r.get('model_stage') in MODEL_STAGES and p is not None)
    if (not historical and not model_fresh) or invalidated or quarantined or safety_review:
        p = None
    if invalidated or quarantined or safety_review:
        fresh = False
    binary = binary_market(r)
    # The saved price may remain visible as an observation. Never calculate
    # current value from a stale quote or invent settlement of integer lines.
    current_value = bool(p is not None and fresh and binary)
    calibrated = number(r.get('calibrated_model_probability'))
    calibrated = calibrated if p is not None and r.get('model_stage') == 'PRODUCTION_APPROVED' and calibrated is not None and 0 < calibrated < 1 else None
    uncertainty = number(r.get('uncertainty'))
    playto = number(r.get('maximum_playable_decimal'))
    books = []
    for book, quote in (r.get('book_prices') or {}).items():
        value = number(quote)
        if value and value > 1:
            books.append({'book': str(book), 'decimal': value})
    # Only expose a projected stat total when the canonical scan contains a
    # version-matched, explicit fitted distribution. A betting line is not a mean.
    distribution = r.get('player_distribution')
    projected_mean = None
    if (isinstance(distribution, dict) and r.get('model_version')
            and distribution.get('model_version') == r.get('model_version')
            and distribution.get('market') == r.get('market')
            and str(r.get('market') or '').removesuffix('_alternate') not in
                {'player_anytime_td', 'player_double_double', 'batter_home_runs'}
            and str(r.get('model_stage')) in MODEL_STAGES
            and (model_fresh or historical)
            and r.get('data_health') == 'HEALTHY'):
        projected_mean = number(distribution.get('mean'))
        if projected_mean is not None and (projected_mean < 0 or projected_mean > 10000):
            projected_mean = None
    from .model_diagnostics import unavailable_reasons, explanation
    missing = unavailable_reasons(
        r, invalidated=invalidated, quarantined=quarantined, safety_review=safety_review,
        model_fresh=model_fresh, model_at=model_at, snapshot_at=record['payload'].get('completed_at'),
        now=now, age_ok=age_ok, stages=MODEL_STAGES) if p is None else []
    return {'id': identity(r), 'snapshot_id': record['id'], 'sport': label, 'event_id': r.get('event_id'),
            'event': str(r.get('event') or ''), 'player': r.get('participant'), 'market': r.get('market'),
            'selection': r.get('selection'), 'line': r.get('line'), 'book': r.get('book'), 'decimal': price,
            'model_probability': p, 'calibrated_probability': calibrated,
            'projected_mean': projected_mean, 'projection_basis': 'FITTED DISTRIBUTION' if projected_mean is not None else None,
            'market_probability': market_p, 'fair_decimal': 1/p if p and binary else None,
            'model_fresh': model_fresh, 'price_fresh': fresh, 'settlement_supported': binary,
            'settlement': r.get('settlement', 'OVER_UNDER'), 'current_decimal': price if fresh else None,
            'source': 'SAVED_MARKET_SCAN', 'team': r.get('team') or (r.get('role_context') or {}).get('team'),
            'edge': p-market_p if current_value and market_p is not None else None,
            'ev': p*price-1 if current_value and price else None, 'play_to_decimal': playto if current_value and playto and playto > 1 else None,
            'model_version': r.get('model_version'), 'model_stage': r.get('model_stage', 'UNAVAILABLE'),
            'probability_kind': ('CALIBRATED' if calibrated is not None
                                 else 'RESEARCH_ONLY' if p is not None else 'UNAVAILABLE'),
            'probability_unavailable_reason': missing[0] if missing else None,
            'probability_unavailable_reasons': missing,
            'probability_unavailable_message': explanation(missing[0]) if missing else None,
            'uncertainty': uncertainty, 'uncertainty_kind': 'policy haircut, not a confidence interval',
            'status': state, 'anomaly_state': anomaly or None, 'fresh': fresh, 'historical': historical, 'lifecycle': 'INVALIDATED' if invalidated else 'HISTORICAL' if historical else 'EXPIRED' if start and start <= now else 'UPCOMING',
            'price_at': r.get('price_time_utc'), 'model_at': model_at, 'injury_at': r.get('injury_time_utc'), 'lineup_at': r.get('lineup_time_utc'), 'weather_at': r.get('weather_time_utc'), 'starts_at': r.get('starts_at_utc'), 'snapshot_at': record['payload'].get('completed_at', record['payload'].get('generated_at')),
            'data_health': r.get('data_health', 'UNKNOWN'), 'approved_for_betting': False,
            'why': ('Historical research snapshot; recheck current evidence.' if historical else
                    'This market is quarantined pending review.' if quarantined else
                    'The research feed is unhealthy; current inputs need verification.' if not record['payload'].get('healthy') else
                    'The research snapshot is stale; waiting for a successful refresh.' if not age_ok(record['payload'].get('completed_at'), now, 10800) else
                    'The sportsbook price needs a fresh check.' if not fresh else
                    'No independent model estimate is available for this exact market and line.' if p is None else
                    'The model is still being evaluated; this is research only.' if r.get('model_stage') == 'VALIDATING' else
                    'Research estimate compared with observed market consensus; not an official wager.'),
            'risks': ['Model estimates may be experimental.', 'Lineup, injury and weather confirmation are not included unless explicitly sourced.'], 'key_factors': list(r.get('key_factors') or [])[:8], 'role_context': r.get('role_context') or {},
            'other_prices': sorted(books, key=lambda b: -b['decimal'])}


def board(store, *, now=None, record=None, historical=False, slate_date=None):
    now = now or datetime.now(UTC)
    day = slate_date or now.astimezone(ZoneInfo('America/Chicago')).date()
    records = store.list_records('research_sheet', 1, entity='latest_scan') if record is None else [record]
    record = records[0] if records else None
    payload = record.get('payload', {}) if record else {}
    raw = payload.get('rows', [])
    raw = raw if isinstance(raw, list) else []
    output = []
    rejected = 0
    for row in raw[:10000]:
        try:
            projected = project(row, record, now, historical, day) if isinstance(row, dict) else None
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            projected = None
            rejected += 1
        if projected:
            output.append(projected)
    sources = [{'source': 'research_sheet', 'snapshot_id': record['id'],
                'snapshot_at': payload.get('completed_at')}] if record else []
    coverage = {}
    if not historical:
        from .research import saved_paid_rows, SPORT_CODES
        paid, coverage, paid_sources = saved_paid_rows(store, now=now, slate_date=day)
        # Do not reuse a saved paid forecast after an observed schedule move,
        # cancellation or explicit mismatch in the ordinary schedule snapshot.
        observed_schedule = payload.get('slate_events', [])
        observed_schedule = observed_schedule if isinstance(observed_schedule, list) else []
        for row in paid:
            code = SPORT_CODES.get(row['sport'])
            canonical = {**row, 'sport': code}
            matches = [e for e in observed_schedule if isinstance(e, dict) and e.get('sport') == code
                       and str(e.get('event_id')) == str(row.get('event_id'))]
            if not matches or (len(matches) == 1 and reconciled_event(canonical, matches, now=now, slate_date=day)):
                output.append(row)
        sources.extend(paid_sources)
    controls = flags(store)
    for row in output:
        if controls.get('pause_all') or controls.get('pause_' + row['sport'].lower()):
            row.update(status='QUARANTINED', fresh=False, price_fresh=False, model_fresh=False,
                       model_probability=None, calibrated_probability=None, fair_decimal=None,
                       projected_mean=None, ev=None, edge=None, play_to_decimal=None, current_decimal=None,
                       probability_unavailable_reason='PUBLISHING_PAUSED',
                       probability_unavailable_reasons=['PUBLISHING_PAUSED'],
                       probability_unavailable_message='Research publication is paused by an administrator.',
                       why='Publishing paused by an administrator.')
    # Dedupe the same exact forecast from shared feeds; do not hide other lines,
    # markets or unders. Retain the more recent valid model record deterministically.
    merged = {}
    for row in output:
        prior = merged.get(row['id'])
        quality = lambda x: (bool(x.get('model_fresh')), bool(x.get('fresh')), x.get('model_at') or '', x.get('price_at') or '')
        if prior is None or quality(row) > quality(prior):
            merged[row['id']] = row
    games = {}
    for event in (payload.get('slate_events') if isinstance(payload.get('slate_events'), list) else []):
        if not isinstance(event, dict) or not eligible_today(event, now=now, slate_date=day):
            continue
        label = sport_label(event.get('sport', ''))
        if label in SPORTS and event.get('event_id'):
            games[(label, str(event['event_id']))] = {'sport': label, 'event_id': str(event['event_id']),
                'event': event.get('event'), 'starts_at': event.get('starts_at_utc') or event.get('starts_at')}
    for row in merged.values():
        games.setdefault((row['sport'], str(row.get('event_id'))),
                         {k: row.get(k) for k in ('sport', 'event_id', 'event', 'starts_at')})
    healthy = bool(record and payload.get('healthy') and age_ok(payload.get('completed_at'), now, 10800))
    partial = bool(payload.get('truncated') or len(raw) > 10000 or rejected or
                   any(v.get('coverage') not in {'FULL', 'NO_ELIGIBLE_GAMES'} or v.get('model_estimates_complete') is False
                       or v.get('snapshot_status') == 'PARTIAL' or v.get('display_truncated')
                       or v.get('malformed_research_rows') for v in coverage.values()))
    return {'state': 'HEALTHY' if healthy and not partial else 'DEGRADED' if sources else 'UNAVAILABLE',
            'date': day.isoformat(), 'rows': list(merged.values()), 'games': list(games.values()),
            'snapshot_id': record['id'] if record else None, 'snapshot_at': payload.get('completed_at'),
            'sources': sources, 'paid_coverage': coverage, 'partial': partial, 'rejected_records': rejected,
            'server_time': now.isoformat(), 'paid_requests_made': 0,
            'reason': ('No saved research snapshot for this date.' if not sources else
                       'No eligible upcoming research rows for the selected date.' if not merged else
                       'Partial coverage; available research remains visible.' if partial or not healthy else None)}


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
        from ..persistence.store import utc
        recorded_at = utc(row['occurred_at']).isoformat() if isinstance(row.get('occurred_at'), datetime) else str(row.get('occurred_at') or '')
        item = project({'sport': price.get('sport'), 'event_id': price.get('event_id'), 'event': price.get('event'),
                        'market': price.get('market'), 'participant': price.get('participant'), 'selection': price.get('selection'), 'line': price.get('line'),
                        'book': price.get('best_book'), 'decimal_odds': price.get('best_decimal'), 'research_probability': p.get('model_probability'),
                        'market_no_vig_probability': price.get('consensus_probability'), 'model_version': p.get('model_version'),
                        'model_stage': p.get('reliability', {}).get('model_stage'), 'price_time_utc': price.get('source_timestamp'),
                        'starts_at_utc': price.get('starts_at'), 'maximum_playable_decimal': p.get('maximum_playable_decimal'),
                        'model_time_utc': recorded_at,
                        'anomaly_state': (p.get('reliability') or {}).get('anomaly_state'),
                        'data_health': ('HEALTHY' if (p.get('reliability', {}).get('research_priority_components') or {}).get('data_health') == 1 else 'UNKNOWN'),
                        'executable': True}, {'id': row['id'], 'payload': {'healthy': True, 'completed_at': recorded_at}}, now)
        if item:
            item.update(id=row['id'], status='BET NOW', approved_for_betting=True, why=str(p.get('reason') or 'Cleared shared cash-authority gates.')[:500])
            output.append(item)
    selected = getattr(store, 'vip_slate_date', None)
    return [r for r in output if selected is None or timestamp(r.get('starts_at')).astimezone(ZoneInfo('America/Chicago')).date() == selected]


def frozen(store, date=None):
    date = date or (getattr(store, 'vip_slate_date', None).isoformat() if getattr(store, 'vip_slate_date', None) else None) or datetime.now(UTC).astimezone(ZoneInfo('America/Chicago')).date().isoformat()
    records = store.list_records('daily_moneyline_sheet', 1, entity=date)
    if not records:
        return {'state': 'UNAVAILABLE', 'date': date, 'rows': [], 'notice': 'The healthy 9 AM CT moneyline sheet has not been published for this date.'}
    record = records[0]
    rows = []
    for raw in record['payload']['rows']:
        value = project({**raw, 'market': 'h2h',
                         'selection': raw.get('projected_winner', raw.get('selection'))},
                        record, datetime.now(UTC), historical=True)
        if value:
            value.update(projection_source=raw.get('projection_source'),
                         confidence=raw.get('confidence'))
            rows.append(value)
    return {'state': 'FROZEN', 'version': '9 AM INITIAL', 'date': date, 'id': record['id'], 'generated_at': record['payload']['generated_at'], 'rows': rows}

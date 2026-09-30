"""Versioned VIP application routes sharing the Discord/worker event store."""
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import member_api
from ..persistence.store import digest
from . import data
from zoneinfo import ZoneInfo
from .state import change_watch, check_watches, owner_key, read_state

router = APIRouter(prefix='/v1/vip')


def context(request: Request):
    store = member_api.store_for_request()
    try:
        principal = member_api.require_member(request, store)
        if request.method not in {'GET', 'HEAD'}:
            member_api.same_origin(request)
        yield store, principal
    finally:
        store.close()


def response(value):
    return JSONResponse(jsonable_encoder(value), headers=member_api.HEADERS)


def snapshot(store):
    b = data.board(store)
    controls = data.flags(store)
    for r in b['rows']:
        if controls.get('pause_all') or controls.get('pause_' + r['sport'].lower()):
            r.update(status='QUARANTINED', fresh=False, why='Publishing paused by an administrator.')
    return b


@router.get('/me')
def me(ctx=Depends(context)):
    store, p = ctx
    return response({'tier': p['tier'], 'expires_at': p['expires_at'], 'preferences': data.preference(store, p),
                     'features': {'research': True, 'watchlist': True, 'admin': p['admin'], 'push_notifications': False}, 'server_time': datetime.now(UTC).isoformat()})


@router.get('/home')
def home(ctx=Depends(context)):
    store, p = ctx
    b = snapshot(store)
    fresh = [r for r in b['rows'] if r['fresh'] and r['status'] != 'QUARANTINED']
    prefs = data.preference(store, p)
    preferred = [r for r in fresh if not prefs.get('sports') or r['sport'] in prefs['sports']]
    preferred.sort(key=lambda r: r['edge'] if r['edge'] is not None else -1, reverse=True)
    picks = data.official(store)
    return response({'state': b['state'], 'snapshot_at': b.get('snapshot_at'), 'server_time': datetime.now(UTC).isoformat(),
                     'research': preferred[:6], 'official': picks[:5], 'top_play': None,
                     'notice': 'Research rankings are not official bets. No top play is assigned without an explicit supported designation.',
                     'sports': [{'sport': s, 'events': len({r['event_id'] or r['event'] for r in b['rows'] if r['sport'] == s}),
                                 'fresh_rows': sum(r['sport'] == s for r in fresh),
                                 'status': 'ACTIVE' if any(r['sport'] == s for r in fresh) else 'UNAVAILABLE'} for s in data.SPORTS],
                     'frozen_available': bool(store.list_records('daily_moneyline_sheet', 1, entity=datetime.now(UTC).astimezone(ZoneInfo('America/Chicago')).date().isoformat()))})


@router.get('/board')
def board(sport: str = '', q: str = Query('', max_length=100), market: str = Query('', max_length=80), status: str = '', sort: Literal['edge', 'time', 'model'] = 'edge', offset: int = Query(0, ge=0, le=10000), ctx=Depends(context)):
    store, _ = ctx
    b = snapshot(store)
    words = data.normalize(q).split()
    rows = [r for r in b['rows'] if (not sport or r['sport'] == sport.upper()) and (not market or r['market'] == market)
            and (not status or r['status'] == status) and all(w in data.normalize(' '.join(str(r.get(k) or '') for k in ('event', 'player', 'market', 'selection', 'sport', 'book'))) for w in words)]
    rows.sort(key=lambda r: (not r['fresh'], -(r.get('model_probability' if sort == 'model' else 'edge') or 0) if sort != 'time' else (r.get('starts_at') or '9999')))
    return response({**{k: v for k, v in b.items() if k != 'rows'}, 'rows': rows[offset:offset+50], 'total': len(rows), 'next': offset+50 if len(rows) > offset+50 else None})


@router.get('/detail/{candidate_id}')
def detail(candidate_id: str, ctx=Depends(context)):
    store, _ = ctx
    b = snapshot(store)
    row = next((r for r in b['rows'] if r['id'] == candidate_id), None)
    if row is None:
        row = next((r for r in data.official(store) if r['id'] == candidate_id), None)
    if row is None:
        raise HTTPException(404, 'This opportunity is no longer in the current research snapshot.')
    related = [r for r in b['rows'] if r['event_id'] == row['event_id'] and r['id'] != row['id']]
    return response({'row': row, 'related': related[:20], 'alternates': [r for r in related if r['player'] == row['player'] and r['market'] == row['market']][:20]})


@router.get('/picks')
def picks(ctx=Depends(context)):
    return response({'rows': data.official(ctx[0]), 'notice': 'Only the same current official candidates eligible for the Discord Main Card. Sprinkles and community bets are excluded.'})


@router.get('/sheets')
def sheets(day: date | None = None, sport: str = '', ctx=Depends(context)):
    result = data.frozen(ctx[0], day.isoformat() if day else None)
    if sport:
        result['rows'] = [r for r in result['rows'] if r['sport'] == sport.upper()]
    return response(result)


@router.get('/archive')
def archive(ctx=Depends(context)):
    # Metadata projection keeps bulky historical slates out of navigation responses.
    from sqlalchemy import select
    from ..persistence.store import events
    with ctx[0].engine.connect() as conn:
        rows = conn.execute(select(events.c.id, events.c.entity, events.c.occurred_at).where(events.c.kind == 'daily_moneyline_sheet').order_by(events.c.occurred_at.desc()).limit(90)).mappings().all()
    return response({'sheets': [dict(r) for r in rows]})


@router.get('/changes')
def changes(ctx=Depends(context)):
    store, _ = ctx
    initial = data.frozen(store)
    latest = snapshot(store)
    if initial['state'] != 'FROZEN':
        return response({'rows': [], 'notice': 'No frozen morning baseline is available today.'})
    before = {(r['sport'], r['event_id'], r['selection']): r for r in initial['rows']}
    changed = []
    for r in latest['rows']:
        old = before.get((r['sport'], r['event_id'], r['selection']))
        if old and r['market'] == 'h2h' and (r['decimal'] != old['decimal'] or r['model_probability'] != old['model_probability']):
            changed.append({'id': r['id'], 'event': r['event'], 'selection': r['selection'], 'before_price': old['decimal'], 'price': r['decimal'], 'before_model': old['model_probability'], 'model': r['model_probability'], 'fresh': r['fresh'], 'price_at': r['price_at']})
    return response({'rows': changed[:100], 'initial_at': initial['generated_at'], 'current_at': latest.get('snapshot_at'), 'notice': 'Compared with the immutable morning moneyline sheet. Quotes may be stale; check each timestamp.'})


@router.get('/top10')
def top10(kind: Literal['hr', 'td', 'nba_props', 'nhl_goals'] = 'hr', ctx=Depends(context)):
    sport, markets = {'hr': ('MLB', {'batter_home_runs'}), 'td': ('NFL', {'player_anytime_td'}), 'nba_props': ('NBA', set()), 'nhl_goals': ('NHL', {'player_goal_scorer_anytime', 'player_goals'})}[kind]
    b = snapshot(ctx[0])
    rows = [r for r in b['rows'] if r['sport'] == sport and (r['market'] in markets if markets else str(r['market']).startswith('player_'))
            and r['fresh'] and r['data_health'] == 'HEALTHY' and r['model_stage'] == 'PRODUCTION_APPROVED' and r['model_probability'] is not None
            and r['status'] not in {'QUARANTINED', 'PASS'}]
    unique = {}
    for r in sorted(rows, key=lambda r: -r['model_probability']):
        unique.setdefault((r['event_id'], r['player'] or r['selection']), r)
    return response({'rows': list(unique.values())[:10], 'kind': kind, 'observed_at': b.get('snapshot_at'), 'notice': 'Up to ten fresh candidates from production-approved player models. Ranked by modeled hit probability; this is not an official bet ranking.'})


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    unit_size: float = Field(30, gt=0, le=100000, allow_inf_nan=False)
    bankroll: float | None = Field(None, gt=0, le=100000000, allow_inf_nan=False)
    sports: list[Literal['MLB', 'NFL', 'CFB', 'NBA', 'NHL', 'WNBA', 'TENNIS', 'SOCCER']] = Field(default_factory=list, max_length=8)
    books: list[str] = Field(default_factory=list, max_length=20)
    teams: list[str] = Field(default_factory=list, max_length=30)
    notifications: bool = True


@router.put('/preferences')
def preferences(body: Preferences, ctx=Depends(context)):
    if any(len(v) > 80 for v in body.books + body.teams):
        raise HTTPException(422, 'Preference text is too long.')
    store, p = ctx
    store.append('vip_preferences', owner_key(p), body.model_dump(), digest(['preferences', owner_key(p), body.model_dump(), datetime.now(UTC).isoformat()]))
    return response(body.model_dump())


class Watch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    minimum_decimal: float | None = Field(None, gt=1, le=10000, allow_inf_nan=False)


@router.get('/watchlist')
def watchlist(ctx=Depends(context)):
    store, p = ctx
    b = snapshot(store)
    check_watches(store, owner_key(p), b)
    watched = read_state(store, 'vip_watchlist', owner_key(p)).get('items', [])
    index = {r['id']: r for r in b['rows']}
    return response({'items': [{**w, 'current': index.get(w['id'])} for w in watched], 'alerts': [r['payload'] for r in store.list_records('vip_notification', 30, entity=owner_key(p))], 'delivery': 'Private in-app inbox. Browser push is not enabled.'})


@router.post('/watchlist')
def add_watch(body: Watch, ctx=Depends(context)):
    store, p = ctx
    row = next((r for r in snapshot(store)['rows'] if r['id'] == body.candidate_id), None)
    if not row:
        raise HTTPException(404, 'Candidate no longer available.')
    try:
        result = change_watch(store, owner_key(p), row, threshold=body.minimum_decimal)
        check_watches(store, owner_key(p), snapshot(store))
        return response(result)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.delete('/watchlist/{candidate_id}')
def remove_watch(candidate_id: str, ctx=Depends(context)):
    return response(change_watch(ctx[0], owner_key(ctx[1]), {'id': candidate_id}, remove=True))


@router.get('/performance')
def performance(ctx=Depends(context)):
    from ..performance import report
    report_data = report(ctx[0])
    return response({'periods': report_data['official_periods'], 'groups': [r for r in report_data['groups'] if r['origin'] == 'scanner'], 'provenance': report_data['provenance'], 'notice': report_data['note'], 'clv': None, 'clv_notice': 'Requires matched official entry and comparable closing evidence.'})


@router.get('/models')
def models(ctx=Depends(context)):
    from ..api import model_status_data
    result = model_status_data()
    return response({'models': [{k: r.get(k) for k in ('sport', 'version', 'status', 'supported_markets', 'player_status', 'player_supported_markets', 'state_refreshed_at', 'market_buckets', 'player_market_buckets')} for r in result['models']], 'has_errors': bool(result.get('errors')), 'controls': data.flags(ctx[0]), 'notice': 'Model readiness is separate from current odds freshness. Model stages are never upgraded by this app.'})


class Control(BaseModel):
    key: Literal['pause_all', 'pause_mlb', 'pause_nfl', 'pause_cfb', 'pause_nba', 'pause_nhl', 'pause_wnba', 'pause_tennis', 'pause_soccer']
    value: bool
    reason: str = Field(min_length=5, max_length=300)


@router.get('/admin')
def admin(ctx=Depends(context)):
    store, p = ctx
    if not p['admin']:
        raise HTTPException(403, 'Administrator access required.')
    return response({'flags': data.flags(store), 'audit': [{'at': r['occurred_at'], **r['payload']} for r in store.list_records('vip_admin_audit', 30)],
                     'capability': 'Pause current app research and new official Discord publication. This does not stop provider ingestion or erase history.'})


@router.post('/admin/control')
def control(body: Control, ctx=Depends(context)):
    store, p = ctx
    if not p['admin']:
        raise HTTPException(403, 'Administrator access required.')
    from sqlalchemy import select
    from ..persistence.store import events
    with store.transaction() as conn:
        row = conn.execute(select(events.c.payload).where(events.c.kind == 'vip_controls', events.c.entity == 'global').order_by(events.c.occurred_at.desc(), events.c.id).limit(1)).first()
        flags = dict((row[0] if row else {}).get('flags', {}))
        before = flags.get(body.key, False)
        flags[body.key] = body.value
        at = datetime.now(UTC).isoformat()
        audit = {'actor': p['member'], 'key': body.key, 'before': before, 'after': body.value, 'reason': body.reason, 'at': at}
        store._append(conn, 'vip_controls', 'global', {'flags': flags}, digest(['control', audit]))
        store._append(conn, 'vip_admin_audit', 'global', audit, digest(['audit', audit]))
    return response({'flags': flags})


class Promo(BaseModel):
    decimal_odds: float = Field(gt=1, le=10000, allow_inf_nan=False)
    boost_percent: float = Field(ge=0, le=1000, allow_inf_nan=False)
    probability: float | None = Field(None, gt=0, lt=1, allow_inf_nan=False)


@router.post('/promo')
def promo(body: Promo, ctx=Depends(context)):
    boosted = 1 + (body.decimal_odds-1)*(1+body.boost_percent/100)
    return response({'boosted_decimal': boosted, 'break_even': 1/boosted, 'original_ev': body.probability*body.decimal_odds-1 if body.probability else None,
                     'boosted_ev': body.probability*boosted-1 if body.probability else None, 'probability_source': 'USER_INPUT_NOT_JABBAZI_MODEL', 'notice': 'Profit-boost calculation only. Confirm eligibility, stake caps and sportsbook terms.'})

@router.get('/search')
def search(q: str = Query('', max_length=100), ctx=Depends(context)):
    store, _ = ctx
    b = snapshot(store)
    words = data.normalize(q).split()
    def matches(r):
        haystack = data.normalize(' '.join(str(r.get(k) or '') for k in ('event', 'player', 'selection', 'market', 'sport', 'book')))
        return all(w in haystack for w in words)
    results = [r for r in b['rows'] if matches(r)]
    results.sort(key=lambda r: (not r['fresh'], r.get('starts_at') or '9999'))
    navigation = []
    for sport in data.SPORTS:
        if not q or sport.lower() in q.lower() or any(r['sport'] == sport for r in results):
            navigation.extend([{'label': sport + ' cheat sheet', 'href': '#sheets&sport=' + sport, 'group': 'CHEAT SHEETS'}, {'label': sport + ' model status', 'href': '#models', 'group': 'MODELS'}])
    return response({'rows': results[:50], 'total': len(results), 'next': None, 'state': b['state'], 'snapshot_at': b.get('snapshot_at'),
                     'groups': {'PLAYERS': list(dict.fromkeys(r['player'] for r in results if r['player']))[:10],
                                'LIVE / UPCOMING': list(dict.fromkeys(r['event'] for r in results if r['lifecycle'] == 'UPCOMING'))[:10]},
                     'navigation': navigation[:16], 'notice': 'Current research searched across supported sports. Expired prices are labeled. Historical sheets have a separate archive.'})

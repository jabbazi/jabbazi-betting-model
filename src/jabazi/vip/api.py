"""Versioned VIP application routes sharing the Discord/worker event store."""
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import member_api
from ..daily_scope import CENTRAL
from ..persistence.store import digest
from . import data
from .state import change_watch, check_watches, owner_key, read_state

router = APIRouter(prefix='/v1/vip')


def context(request: Request, slate_date: date | None = Query(None)):
    from .slate_clock import default_slate_date
    store = member_api.store_for_request()
    try:
        principal = member_api.require_member(request, store)
        if request.method in {'GET', 'HEAD'}:
            store.vip_slate_date = slate_date or default_slate_date()
        if request.method not in {'GET', 'HEAD'}:
            member_api.same_origin(request)
        yield store, principal
    finally:
        store.close()


def response(value):
    return JSONResponse(jsonable_encoder(value), headers=member_api.HEADERS)


def snapshot(store):
    b = data.board(store, slate_date=getattr(store, 'vip_slate_date', None))
    b['date'] = str(getattr(store, 'vip_slate_date', datetime.now(UTC).date()))
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
    """Fast authenticated shell; large research snapshots load on demand.

    The former home endpoint projected the entire latest research slate and
    official candidates before first paint. Under large feeds that could
    exhaust the request timeout despite successful VIP authentication.
    """
    return response({
        'state': 'ON_DEMAND',
        'snapshot_at': None,
        'server_time': datetime.now(UTC).isoformat(),
        'research': [],
        'official': [],
        'top_play': None,
        'notice': 'VIP access is ready. Open a sport or the research board to load its latest evidence. Research projections are not automatically official bets.',
        'sports': [{'sport': sport, 'events': None, 'fresh_rows': None, 'status': 'CHECK ON OPEN'} for sport in data.SPORTS],
        'frozen_available': False,
        'load_strategy': 'on_demand',
     })

@router.get('/today')
def today(ctx=Depends(context)):
    from .game_research import matchups as list_matchups
    from ..performance import report
    b = snapshot(ctx[0])
    issued = {r['entity'] for r in ctx[0].list_records('official_pick_issued', 500) if r['payload'].get('message_id')}
    official = [r for r in data.official(ctx[0]) if r['id'] in issued]
    return response({'games': list_matchups(b['rows']), 'research': b['rows'][:8],
                     'official': official, 'recap': report(ctx[0])['official_periods'][0],
                     'state': b['state'], 'snapshot_at': b.get('snapshot_at'),
                     'reason': b.get('reason'), 'live_notice': 'Live recommendations are not connected to this pregame board.'})


@router.get('/board')
def board(sport: str = '', event_id: str = Query('', max_length=160), q: str = Query('', max_length=100), market: str = Query('', max_length=80), family: Literal['all', 'props'] = 'all', status: str = '', sort: Literal['edge', 'time', 'model'] = 'edge', offset: int = Query(0, ge=0, le=10000), ctx=Depends(context)):
    store, _ = ctx
    b = snapshot(store)
    words = data.normalize(q).split()
    rows = [r for r in b['rows'] if (not sport or r['sport'] == sport.upper()) and (not event_id or str(r.get('event_id')) == event_id) and (not market or r['market'] == market)
            and (family == 'all' or str(r['market']).startswith(('player_', 'batter_', 'pitcher_')))
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
    rows = data.official(ctx[0])
    issued = {r['entity'] for r in ctx[0].list_records('official_pick_issued', 500) if r['payload'].get('message_id')}
    for row in rows:
        row['graphic_available'] = row['id'] in issued
    return response({'rows': rows, 'notice': 'Current qualified Main Card candidates. Official graphics require recorded issuance; sprinkles and community bets are excluded.'})


@router.get('/playoftheday')
def play_of_the_day(ctx=Depends(context)):
    from zoneinfo import ZoneInfo
    today = getattr(ctx[0], 'vip_slate_date', datetime.now(UTC).astimezone(ZoneInfo('America/Chicago')).date()).isoformat()
    issued = ctx[0].list_records('play_of_day', 1, entity=today)
    if not issued:
        return response({'date': today, 'state': 'PASS', 'play': None,
                         'notice': 'No officially issued Play of the Day. We never force a selection.'})
    record = issued[0]
    candidate_id = str(record['payload'].get('candidate_id') or '')
    official = next((r for r in data.official(ctx[0]) if r['id'] == candidate_id), None)
    if official is None:
        return response({'date': today, 'state': 'UNAVAILABLE', 'play': None,
                         'notice': 'The recorded selection is no longer an active official position; original history is preserved.'})
    return response({'date': today, 'state': 'ISSUED', 'play': official,
                     'notice': 'An official JABBAZI-issued position; respect its play-to price.'})


@router.get('/sheets')
def sheets(day: date | None = None, sport: str = '', ctx=Depends(context)):
    result = data.frozen(ctx[0], day.isoformat() if day else None)
    if sport:
        result['rows'] = [r for r in result['rows'] if r['sport'] == sport.upper()]
    return response(result)


@router.get('/pick-graphic/{candidate_id}')
def pick_graphic(candidate_id: str, kind: Literal['official', 'playoftheday'] = 'official', ctx=Depends(context)):
    from fastapi.responses import Response
    from ..daily_scope import CENTRAL
    from .graphics import approved_logo_path, render_research_card
    store, _ = ctx
    row = next((r for r in data.official(store) if r['id'] == candidate_id), None)
    if row is None:
        raise HTTPException(404, 'No current qualified official candidate for this graphic.')
    if kind == 'playoftheday':
        issued = store.list_records('play_of_day', 1, entity=datetime.now(CENTRAL).date().isoformat())
        verified = bool(issued and issued[0]['payload'].get('candidate_id') == candidate_id)
    else:
        issued = store.list_records('official_pick_issued', 1, entity=candidate_id)
        verified = bool(issued and issued[0]['payload'].get('message_id'))
    if not verified:
        raise HTTPException(409, 'Official issuance evidence is required. Research candidates cannot be exported as official picks.')
    lines = [row['event'], f"{row['selection']} {row.get('line') if row.get('line') is not None else ''}",
             'Market: '+str(row['market']), 'Start: '+str(row['starts_at']),
             f"Observed decimal odds: {row['decimal']} • {row['book']}",
             'Price observed: '+str(row['price_at']), 'Model: '+str(row['model_version']),
             'Status: '+str(row['model_stage']), 'Issued: '+str(issued[0]['occurred_at'])]
    try:
        png = render_research_card('PLAY OF THE DAY' if kind == 'playoftheday' else 'OFFICIAL JABBAZI PICK',
                                  lines, approved_logo_path(), notice='OFFICIALLY ISSUED • SNAPSHOT PRICE • RECHECK BEFORE USE')
    except (OSError, ValueError):
        raise HTTPException(503, 'Approved brand asset unavailable.')
    return Response(png, media_type='image/png', headers={'Cache-Control': 'private, no-store'})


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


@router.get('/slate')
def slate(sport: str, ctx=Depends(context)):
    b = snapshot(ctx[0])
    sport = sport.upper()
    rows = [r for r in b['rows'] if r['sport'] == sport and r['lifecycle'] == 'UPCOMING']
    games = {}
    for r in rows:
        key = r['event_id'] or r['event']
        game = games.setdefault(key, {'event_id': r['event_id'], 'event': r['event'], 'starts_at': r['starts_at'], 'markets': set()})
        game['markets'].add(r['market'])
    output = []
    for game in sorted(games.values(), key=lambda g: g.get('starts_at') or '9999'):
        game['markets'] = sorted(game['markets'])
        output.append(game)
    return response({'sport': sport, 'games': output, 'snapshot_at': b.get('snapshot_at'), 'state': b['state']})


@router.get('/matchups')
def matchups(sport: str = Query('', max_length=12), ctx=Depends(context)):
    from .game_research import matchups as list_matchups
    b = snapshot(ctx[0])
    return response({'state': b['state'], 'snapshot_at': b.get('snapshot_at'),
                     'games': list_matchups(b['rows'], sport=sport, limit=100),
                     'notice': 'Observed research events only. Matchups are not official wagers.'})


@router.get('/matchup/{sport}/{event_id}')
def matchup(sport: str, event_id: str, ctx=Depends(context)):
    from .game_research import matchup_detail
    b = snapshot(ctx[0])
    result = matchup_detail(b['rows'], sport.upper(), event_id)
    if result is None:
        raise HTTPException(404, 'No observed research for this matchup.')
    issued = {r['entity'] for r in ctx[0].list_records('official_pick_issued', 500) if r['payload'].get('message_id')}
    official = [r for r in data.official(ctx[0]) if r['id'] in issued and r['sport'] == sport.upper() and str(r['event_id']) == event_id]
    from .rankings import research_hub
    hub = research_hub(b['rows'], sport=sport.upper(), event_id=event_id,
                       slate_date=getattr(ctx[0], 'vip_slate_date', None), source_picks=ctx[0].list_records('source_pick', 200))
    if not result['projection']['selection'] and hub['web_leans']:
        result['projection'].update(selection=hub['web_leans'][0]['selection'], source='WEB-RESEARCH LEAN')
        from .game_research import projection_reason
        result['pick_explanation'] = projection_reason(result['projection'], evidence=hub['web_leans'][0])
    result['research_evidence'] = hub['web_leans']
    result['research_conflicts'] = hub['conflicting_events']
    sheet = data.frozen(ctx[0])
    sheet_card = next((r for r in sheet['rows'] if r['sport'] == sport.upper() and str(r['event_id']) == event_id), None)
    return response({**result, 'snapshot_at': b.get('snapshot_at'), 'official': official,
                     'cheatsheet_available': sheet_card is not None,
                     'lineup_notice': 'Confirmed injury and lineup evidence is not supplied by this matchup summary. Check individual research provenance; missing evidence remains unavailable.',
                     'notice': 'Projections and market observations are research only. Do not treat these as issued bets.'})


@router.get('/slate.png')
def slate_graphic(ctx=Depends(context)):
    from fastapi.responses import Response
    from ..discord_daily import daily_moneyline, render_slate
    from ..daily_scope import eligible_today, delivery_eligible
    if getattr(ctx[0], 'vip_slate_date', None) != datetime.now(CENTRAL).date():
        raise HTTPException(404, 'The selected date’s complete slate graphic is not available yet. Research previews remain available.')
    record = daily_moneyline(ctx[0])
    if record is None:
        raise HTTPException(404, 'Today’s daily slate has not been generated yet.')
    rows = [r for r in record['payload'].get('rows', []) if eligible_today(r)]
    if rows and not delivery_eligible(ctx[0], rows):
        raise HTTPException(409, 'The game schedule changed. A fresh matching slate is required.')
    record = {**record, 'payload': {**record['payload'], 'rows': rows, 'row_count': len(rows)}}
    return Response(render_slate(record), media_type='image/png', headers=member_api.HEADERS)


@router.get('/graphic/{sport}/{event_id}')
def matchup_graphic(sport: str, event_id: str,
                    kind: Literal['matchup', 'simulation', 'cheatsheet'] = 'matchup',
                    day: date | None = None, ctx=Depends(context)):
    from fastapi.responses import Response
    from .game_research import matchup_detail
    from .graphics import render_matchup, render_research_card
    b = snapshot(ctx[0])
    detail = matchup_detail(b['rows'], sport.upper(), event_id)
    if detail:
        detail['snapshot_at'] = b.get('snapshot_at')
    if detail is None and kind != 'cheatsheet':
        raise HTTPException(404, 'No observed research for this matchup.')
    from .graphics import approved_logo_path
    approved_logo = approved_logo_path()
    if not approved_logo:
        raise HTTPException(503, 'The approved JABBAZI logo asset has not been installed.')
    try:
        if kind == 'simulation':
            from .game_research import simulate_current_event
            sim = simulate_current_event(ctx[0], sport=sport.upper(), event_id=event_id, rows=b['rows'])
            if not sim.get('summary'):
                raise HTTPException(503, 'No supported score distribution for this graphic.')
            summary = sim['summary']
            lines = [detail['event'], 'Model: '+sim['model_version'],
                     f"{sim['home']}: {summary['expected_home_points']:.1f}",
                     f"{sim['away']}: {summary['expected_away_points']:.1f}",
                     f"Home win: {sim['home_win']['win']:.1%} | Away win: {sim['away_win']['win']:.1%}",
                     f"Projected total: {summary['expected_total']:.1f}",
                     'Snapshot: '+str(b.get('snapshot_at'))]
            graphic = render_research_card('GAME SIM • SHADOW ONLY', lines, approved_logo)
        elif kind == 'cheatsheet':
            sheet = data.frozen(ctx[0], day.isoformat() if day else None)
            card = next((r for r in sheet['rows'] if r['sport'] == sport.upper() and str(r['event_id']) == event_id), None)
            if card is None:
                raise HTTPException(404, 'No cheat-sheet card for this game on the requested Central date.')
            graphic = render_research_card('DAILY CHEAT SHEET • '+sheet['date'],
                [card['event'], 'Projected winner: '+str(card['selection'] or 'Unavailable'),
                 'Confidence: '+str(card.get('confidence') or 'Unavailable'),
                 'Source: '+str(card.get('projection_source') or 'Unavailable'),
                 'Frozen: '+str(sheet.get('generated_at'))], approved_logo)
        else:
            graphic = render_matchup(detail, approved_logo)
    except (OSError, ValueError):
        raise HTTPException(503, 'The approved logo asset is not available for rendering.')
    return Response(content=graphic, media_type='image/png', headers={
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'
    })


@router.get('/sim/{sport}/{event_id}')
def simulation(sport: str, event_id: str,
               spread_line: float | None = Query(None, ge=-300, le=300, allow_inf_nan=False),
               total_line: float | None = Query(None, ge=0, le=500, allow_inf_nan=False),
               ctx=Depends(context)):
    from .game_research import matchup_detail, simulate_current_event
    b = snapshot(ctx[0])
    result = matchup_detail(b['rows'], sport.upper(), event_id)
    if result is None:
        raise HTTPException(404, 'No observed research for this matchup.')
    simulation_result = simulate_current_event(ctx[0], sport=sport.upper(), event_id=event_id, rows=b['rows'],
                                               spread_line=spread_line, total_line=total_line)
    return response({'event': result['event'], 'event_id': event_id,
                     **simulation_result,
                     'notice': 'Only verified event-matched paired score distributions are shown. Model output remains SHADOW_ONLY research.'})


@router.get('/firsttd/{event_id}')
def firsttd(event_id: str, ctx=Depends(context)):
    from .game_research import matchup_detail
    b = snapshot(ctx[0])
    result = matchup_detail(b['rows'], 'NFL', event_id)
    if result is None:
        raise HTTPException(404, 'No observed NFL research for this matchup.')
    return response({'event': result['event'], 'event_id': event_id,
                     **result['first_td'],
                     'notice': 'First touchdown is distinct from anytime touchdown. No unsupported rankings are displayed.'})


@router.get('/rankings')
def rankings(sport: str = Query('', max_length=12), event_id: str = Query('', max_length=160), ctx=Depends(context)):
    from .rankings import research_hub
    b = snapshot(ctx[0])
    return response({**research_hub(b['rows'], sport=sport, event_id=event_id,
                                   slate_date=getattr(ctx[0], 'vip_slate_date', None), source_picks=ctx[0].list_records('source_pick', 200)),
                     'snapshot_at': b.get('snapshot_at'), 'state': b['state']})


@router.get('/top10')
def top10(kind: Literal['hr', 'td', 'nba_props', 'nhl_goals'] = 'hr', ctx=Depends(context)):
    sport, markets = {'hr': ('MLB', {'batter_home_runs'}), 'td': ('NFL', {'player_anytime_td'}), 'nba_props': ('NBA', set()), 'nhl_goals': ('NHL', {'player_goal_scorer_anytime', 'player_goals'})}[kind]
    b = snapshot(ctx[0])
    rows = [r for r in b['rows'] if r['sport'] == sport and (r['market'] in markets if markets else str(r['market']).startswith('player_'))
            and r['fresh'] and r['data_health'] == 'HEALTHY' and r['model_stage'] == 'PRODUCTION_APPROVED' and r['model_probability'] is not None
            and r['status'] not in {'QUARANTINED', 'PASS'}]
    unique = {}
    def ranking_value(r):
        # Price-aware ranking: prefer expected value when both a calibrated/model
        # probability and executable price exist. Probability is only a fallback.
        p = r.get('calibrated_probability') or r.get('model_probability')
        ev = (p * r['decimal'] - 1) if p is not None and r.get('decimal') else None
        return (ev if ev is not None else -1.0, p if p is not None else -1.0)
    for r in sorted(rows, key=ranking_value, reverse=True):
        unique.setdefault((r['event_id'], r['player'] or r['selection']), r)
    return response({'rows': list(unique.values())[:10], 'kind': kind, 'observed_at': b.get('snapshot_at'), 'notice': 'Up to ten fresh candidates from production-approved player models. Ranked by price-aware expected value when available, then calibrated/model probability. This is research, not an automatic wager ranking.'})


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    unit_size: float = Field(30, gt=0, le=100000, allow_inf_nan=False)
    bankroll: float | None = Field(None, gt=0, le=100000000, allow_inf_nan=False)
    sports: list[Literal['MLB', 'NFL', 'CFB', 'NBA', 'NHL', 'WNBA', 'TENNIS', 'SOCCER']] = Field(default_factory=list, max_length=8)
    books: list[str] = Field(default_factory=list, max_length=20)
    teams: list[str] = Field(default_factory=list, max_length=30)
    notifications: bool = True
    discord_dm: bool = False
    alert_categories: list[Literal['price', 'status']] = Field(default_factory=lambda: ['price', 'status'], max_length=2)
    quiet_start: int | None = Field(None, ge=0, le=23)
    quiet_end: int | None = Field(None, ge=0, le=23)

    @model_validator(mode='after')
    def quiet_pair(self):
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError('Set both quiet-hour boundaries or neither')
        if self.quiet_start is not None and self.quiet_start == self.quiet_end:
            raise ValueError('Quiet-hour boundaries must differ; disable notifications to mute all day')
        return self


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
    from ..daily_scope import eligible_today
    store, p = ctx
    b = snapshot(store)
    check_watches(store, owner_key(p), b)
    watched = read_state(store, 'vip_watchlist', owner_key(p)).get('items', [])
    index = {r['id']: r for r in b['rows']}
    return response({'items': [{**w, 'current': index.get(w['id'])} for w in watched], 'alerts': [r['payload'] for r in store.list_records('vip_notification', 30, entity=owner_key(p)) if eligible_today(r['payload'])], 'delivery': 'Private in-app inbox for today’s upcoming games. Historical records are retained; browser push is not enabled.'})


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


@router.get('/performance-graphic')
def performance_graphic(period: Literal['Today', 'This week', 'This month', 'All time'] = 'Today', ctx=Depends(context)):
    from ..performance import report
    from .graphics import approved_logo_path, render_research_card
    from fastapi.responses import Response
    result = report(ctx[0])
    cohort = next(p for p in result['official_periods'] if p['label'] == period)
    if not sum(g['settled'] for g in cohort['groups']):
        raise HTTPException(503, 'No settled official ledger evidence for this period. Missing records do not imply zero bets.')
    lines = [cohort['from']+' through '+cohort['through'], 'OWNER-REPORTED • SCANNER POSITIONS ONLY']
    for group in cohort['groups']:
        roi = f"{group['roi']:.1%}" if group['roi'] is not None else 'Unavailable'
        lines.extend([f"{group['kind']}: {group['wins']}W / {group['losses']}L / {group['pushes_or_voids']} push or void",
                      f"Net: {group['profit_units']:+.2f}u | ROI: {roi} | Settled: {group['settled']}"])
    lines.append('CLV: unavailable without matched closing evidence')
    try:
        png = render_research_card('PERFORMANCE • '+period.upper(), lines, approved_logo_path(),
                                  notice='SETTLED RECORDS ONLY • OPEN POSITIONS EXCLUDED • COVERAGE MAY BE INCOMPLETE')
    except (OSError, ValueError):
        raise HTTPException(503, 'Approved brand asset unavailable.')
    return Response(png, media_type='image/png', headers={'Cache-Control': 'private, no-store'})


@router.get('/ask')
def ask(q: str = Query('', min_length=2, max_length=200), ctx=Depends(context)):
    """Evidence-grounded helper for common VIP research questions.

    This intentionally does not call a generative model. It answers only from
    canonical stored evidence so it cannot invent probabilities.
    """
    store, _ = ctx
    b = snapshot(store)
    query = data.normalize(q)
    rows = b['rows']
    if 'touchdown' in query or ' td ' in (' ' + query + ' '):
        kind, sport, markets = 'NFL anytime TD', 'NFL', {'player_anytime_td'}
    elif 'home run' in query or ' hr ' in (' ' + query + ' '):
        kind, sport, markets = 'MLB home run', 'MLB', {'batter_home_runs'}
    elif 'goal scorer' in query:
        kind, sport, markets = 'NHL goal scorer', 'NHL', {'player_goal_scorer_anytime', 'player_goals'}
    else:
        kind, sport, markets = 'research', None, None
    candidates = [r for r in rows if (not sport or r['sport'] == sport) and (not markets or r['market'] in markets)
                  and r['fresh'] and r['status'] != 'QUARANTINED']
    words = [w for w in query.split() if len(w) > 2 and w not in {'show', 'what', 'which', 'why', 'model', 'research'}]
    if words:
        matched = [r for r in candidates if all(w in data.normalize(' '.join(str(r.get(k) or '') for k in ('event','player','selection','market','sport'))) for w in words)]
        if matched:
            candidates = matched
    candidates.sort(key=lambda r: ((r.get('calibrated_probability') or r.get('model_probability') or 0) * (r.get('decimal') or 1) - 1), reverse=True)
    return response({'question': q, 'kind': kind, 'rows': candidates[:10], 'snapshot_at': b.get('snapshot_at'),
                     'answer': 'Showing current canonical JABBAZI evidence only. Missing model or market evidence remains unavailable.',
                     'notice': 'ASK JABBAZI does not invent probabilities or override BET/WATCH/PASS/model-stage controls.'})


@router.get('/models')
def models(ctx=Depends(context)):
    from ..api import model_status_data
    from .model_cache import status
    current = status(model_status_data)
    if current['data'] is None:
        return response({'state': current['state'], 'models': [], 'has_errors': True, 'controls': {},
                         'notice': 'Model evidence is refreshing in the background. No unverified model probability is shown. Reopen this view shortly.'})
    result = current['data']
    return response({'state': 'READY', 'models': [{**{k: r.get(k) for k in ('sport', 'version', 'status', 'supported_markets', 'player_status', 'player_supported_markets', 'state_refreshed_at', 'market_buckets', 'player_market_buckets')}, 'sport': data.sport_label(r.get('sport', ''))} for r in result['models']], 'has_errors': bool(result.get('errors')), 'controls': data.flags(ctx[0]), 'notice': 'Model readiness is separate from current odds freshness. Model stages are never upgraded by this app.'})


class Control(BaseModel):
    key: Literal['pause_all', 'pause_mlb', 'pause_nfl', 'pause_cfb', 'pause_nba', 'pause_nhl', 'pause_wnba', 'pause_tennis', 'pause_soccer']
    value: bool
    reason: str = Field(min_length=5, max_length=300)


@router.get('/admin')
def admin(ctx=Depends(context)):
    store, p = ctx
    if not p['admin']:
        raise HTTPException(403, 'Administrator access required.')
    from .operations import health
    import os
    is_owner = str(p['member']) == os.getenv('JABBAZI_DISCORD_OWNER_ID', '')
    return response({'health': health(store) if is_owner else None, 'flags': data.flags(store), 'audit': [{'at': r['occurred_at'], **r['payload']} for r in store.list_records('vip_admin_audit', 30)],
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

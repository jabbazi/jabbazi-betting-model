"""Read-only, canonical research queries shared by VIP and Discord.

These projections never fetch providers, change model approval, or issue picks.
The input is the already permission-scoped saved research board.
"""
from collections import Counter
from urllib.parse import urlencode

from . import data

MODEL_STAGES = {'SHADOW_ONLY', 'VALIDATING', 'LIMITED_LIVE', 'PRODUCTION_APPROVED'}
BLOCKED = {'INVALIDATED', 'QUARANTINED', 'SAFETY REVIEW'}
SPORT_CODES = {'NBA': 'basketball_nba', 'NFL': 'americanfootball_nfl',
               'NHL': 'icehockey_nhl', 'MLB': 'baseball_mlb', 'CFB': 'americanfootball_ncaaf'}
MARKETS = {
    'NBA': ('player_points', 'player_rebounds', 'player_assists', 'player_threes',
            'player_points_rebounds_assists', 'player_points_rebounds', 'player_points_assists',
            'player_rebounds_assists', 'player_steals', 'player_blocks', 'player_turnovers', 'player_double_double'),
    'NFL': ('player_pass_yds', 'player_pass_tds', 'player_pass_attempts', 'player_pass_completions',
            'player_rush_yds', 'player_rush_attempts', 'player_reception_yds', 'player_receptions', 'player_anytime_td'),
    'NHL': ('player_shots_on_goal', 'player_goals', 'player_points', 'player_assists', 'player_total_saves'),
    'MLB': ('batter_hits', 'batter_total_bases', 'batter_home_runs', 'batter_rbis', 'batter_runs_scored',
            'batter_walks', 'batter_hits_runs_rbis', 'pitcher_strikeouts', 'pitcher_outs', 'pitcher_hits_allowed', 'pitcher_walks'),
    'CFB': (),
}


def usable_model(row):
    p = data.number(row.get('model_probability'))
    return bool(row.get('model_stage') in MODEL_STAGES
                and row.get('status') not in BLOCKED
                and row.get('data_health') == 'HEALTHY'
                and row.get('model_version') and p is not None and 0 < p < 1
                and row.get('model_fresh', row.get('fresh', False)))


def binary_market(row):
    """Do not invent push handling for integer-line O/U or spread markets."""
    if row.get('settlement') in {'BINARY', 'AT_LEAST'} or row.get('market') == 'h2h':
        return True
    line = data.number(row.get('line'))
    return line is not None and abs(line % 1 - .5) < 1e-9


def saved_paid_rows(store, *, now, slate_date):
    """Normalize all saved fitted research rows, not a truncated Top 10 list.

    Read the latest record for each sport from bounded recent snapshots, so a
    single-sport refresh cannot erase other sports. Newest explicit empty data
    wins over older data. No fallback to yesterday or private raw quote events.
    """
    records = store.list_records('paid_player_scan', 20, entity=slate_date.isoformat())
    output, coverage, snapshots, seen = [], {}, [], set()
    for record in records:
        payload = record.get('payload')
        if not isinstance(payload, dict) or payload.get('slate_date') != slate_date.isoformat():
            continue
        buckets = payload.get('sports')
        if not isinstance(buckets, dict):
            continue
        for sport, bucket in buckets.items():
            if sport not in {'NBA', 'NFL', 'NHL'} or sport in seen or not isinstance(bucket, dict):
                continue
            seen.add(sport)
            coverage[sport] = {k: bucket.get(k) for k in (
                'coverage', 'eligible_games', 'accepted_quotes', 'model_probability_rows', 'model_estimates_complete')}
            coverage[sport]['snapshot_status'] = payload.get('status')
            coverage[sport]['display_truncated'] = isinstance(bucket.get('research_rows'), list) and len(bucket['research_rows']) > 10000
            snapshots.append({'source': 'paid_player_scan', 'sport': sport,
                              'snapshot_id': record['id'], 'snapshot_at': payload.get('observed_at')})
            rows = bucket.get('research_rows')
            if not isinstance(rows, list):
                continue
            source_record = {'id': record['id'], 'payload': {
                'healthy': True, 'completed_at': payload.get('observed_at')}}
            # An individual fitted record may be sound even when other markets
            # are missing. Incomplete collection is still reported separately.
            for raw in rows[:10000]:
                if not isinstance(raw, dict) or raw.get('probability_basis') != 'FITTED_JABBAZI_MODEL':
                    continue
                if raw.get('sport') not in {sport, SPORT_CODES[sport]}:
                    continue
                model_at = data.timestamp(raw.get('model_time'))
                if not model_at or not 0 <= (now-model_at).total_seconds() <= 3600:
                    continue
                projected = raw.get('projected_mean')
                normalized = {
                    **raw, 'sport': SPORT_CODES[sport], 'participant': raw.get('participant'),
                    'research_probability': raw.get('model_probability'),
                    'starts_at_utc': raw.get('starts_at'),
                    'price_time_utc': raw.get('source_timestamp'), 'model_time_utc': raw.get('model_time'),
                    'decimal_odds': raw.get('decimal_odds', raw.get('best_decimal', raw.get('offered_decimal', raw.get('decimal')))),
                    'book': raw.get('book', raw.get('best_sportsbook', raw.get('sportsbook'))), 'data_health': raw.get('data_health', 'HEALTHY'),
                    'executable': False, 'price_stale': not data.age_ok(raw.get('source_timestamp'), now, 120),
                    'player_distribution': {'mean': projected, 'market': raw.get('market'), 'model_version': raw.get('model_version')},
                }
                try:
                    row = data.project(normalized, source_record, now, slate_date=slate_date)
                except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                    coverage[sport]['malformed_research_rows'] = coverage[sport].get('malformed_research_rows', 0) + 1
                    continue
                if row:
                    row.update(source='SAVED_PAID_MODEL_RESEARCH', executable_sportsbook_ticket_verified=False)
                    output.append(row)
    return output, coverage, snapshots


def query_board(board, *, sport='', event_id='', family='all', q='', market='',
                player='', team='', side='', book='', stage='', status='', sort='model', offset=0, limit=50):
    """Filter the entire permitted saved board before deterministic pagination."""
    scoped = [r for r in board['rows'] if (not sport or r['sport'] == sport.upper())
              and (not event_id or str(r.get('event_id')) == event_id)
              and (family != 'props' or str(r.get('market', '')).startswith(('player_', 'batter_', 'pitcher_')))]
    def count(field):
        return [{'value': value, 'count': n} for value, n in sorted(Counter(
            str(r.get(field)) for r in scoped if r.get(field) is not None and r.get(field) != '').items())]
    facets = {name: count(field) for name, field in (
        ('markets', 'market'), ('players', 'player'), ('games', 'event'), ('books', 'book'),
        ('stages', 'model_stage'), ('sides', 'selection'), ('teams', 'team'))}
    games = {}
    for row in scoped:
        games.setdefault(str(row.get('event_id')), {'value': str(row.get('event_id')), 'label': row.get('event'), 'count': 0})['count'] += 1
    facets['games'] = [games[k] for k in sorted(games)]
    observed = Counter(r['market'] for r in scoped)
    catalog = sorted(set(MARKETS.get(sport.upper(), ())) | set(observed)) if family == 'props' else sorted(observed)
    facets['markets'] = [{'value': m, 'count': observed[m],
                         'state': 'AVAILABLE' if observed[m] else 'NO_SAVED_ROWS'} for m in catalog]
    words = data.normalize(q).split()
    rows = [r for r in scoped if (not market or r.get('market') == market)
            and (not player or str(r.get('player') or '').casefold() == player.casefold())
            and (not team or team.casefold() in str(r.get('team') or '').casefold())
            and (not side or str(r.get('selection') or '').casefold() == side.casefold())
            and (not book or str(r.get('book') or '').casefold() == book.casefold()
                 or any(str(p.get('book', '')).casefold() == book.casefold() for p in r.get('other_prices', [])))
            and (not stage or r.get('model_stage') == stage)
            and (not status or r.get('status') == status)
            and all(w in data.normalize(' '.join(str(r.get(k) or '') for k in (
                'event', 'player', 'market', 'selection', 'sport', 'book', 'team'))) for w in words)]
    def ordering(r):
        value = r.get('model_probability' if sort == 'model' else 'projected_mean' if sort == 'projection' else 'ev' if sort == 'value' else 'edge')
        return ((r.get('starts_at') or '9999', str(r.get('id'))) if sort == 'time' else
                (value is None, -(value or 0), r.get('starts_at') or '9999', str(r.get('id'))))
    if sort == 'projection':
        rows = [r for r in rows if r.get('projected_mean') is not None and r.get('projection_basis') == 'FITTED DISTRIBUTION']
    if sort == 'value':
        rows = [r for r in rows if r.get('model_stage') == 'PRODUCTION_APPROVED' and r.get('fresh')
                and r.get('ev') is not None and r['ev'] > 0]
    rows.sort(key=ordering)
    return {**{k: v for k, v in board.items() if k not in {'rows', 'games'}},
            'rows': rows[offset:offset+limit], 'total': len(rows), 'offset': offset, 'page_size': limit,
            'next': offset+limit if offset+limit < len(rows) else None,
            'facets': facets, 'scope_total': len(scoped),
            'empty_reason': ('NO_FILTER_MATCHES' if scoped else 'NO_SAVED_RESEARCH') if not rows else None,
            'paid_requests_made': 0}


def moneyline_board(board, *, sport='', sort='model', offset=0, limit=50):
    """All observed scheduled games, with model winner and market lean separated."""
    games = {(g['sport'], str(g['event_id'])): dict(g) for g in board.get('games', [])
             if not sport or g['sport'] == sport.upper()}
    grouped = {}
    for row in board['rows']:
        if sport and row['sport'] != sport.upper():
            continue
        key = (row['sport'], str(row.get('event_id')))
        games.setdefault(key, {k: row.get(k) for k in ('sport', 'event_id', 'event', 'starts_at')})
        if row.get('market') == 'h2h':
            grouped.setdefault(key, []).append(row)
    result = []
    for key, game in games.items():
        rows = grouped.get(key, [])
        model_rows = [r for r in rows if usable_model(r)]
        model = max(model_rows, key=lambda r: (r['model_probability'], str(r['id'])), default=None)
        market_rows = [r for r in rows if r.get('fresh') and r.get('market_probability') is not None and r.get('status') not in BLOCKED]
        market = max(market_rows, key=lambda r: r['market_probability'], default=None)
        values = [r for r in model_rows if r.get('model_stage') == 'PRODUCTION_APPROVED'
                  and r.get('fresh') and r.get('ev') is not None and r['ev'] > 0]
        best_value = max(values, key=lambda r: r['ev'], default=None)
        result.append({**game, 'predicted_winner': model.get('selection') if model else None,
                       'model_probability': model.get('model_probability') if model else None,
                       'model': model, 'market_lean': market, 'best_value': best_value,
                       'reason': None if model else ('No saved moneyline forecast for this game.' if not rows
                                                    else rows[0].get('probability_unavailable_reason') or 'No current valid model forecast.'),
                       'model_rows': len(model_rows), 'observed_rows': len(rows), 'approved_for_betting': False})
    if sort == 'value':
        result = [g for g in result if g['best_value']]
        result.sort(key=lambda g: (-g['best_value']['ev'], str(g['event_id'])))
    elif sort == 'time':
        result.sort(key=lambda g: (g.get('starts_at') or '9999', str(g['event_id'])))
    else:
        result.sort(key=lambda g: (g['model_probability'] is None, -(g['model_probability'] or 0),
                                   g.get('starts_at') or '9999', str(g['event_id'])))
    return {**{k: v for k, v in board.items() if k not in {'rows', 'games'}},
            'games': result[offset:offset+limit], 'total': len(result), 'offset': offset,
            'next': offset+limit if offset+limit < len(result) else None,
            'paid_requests_made': 0, 'notice': 'Model winners and market leans are separate. Research is not an official pick.'}


def research_link(view, *, sport='', market='', slate_date=None):
    params = {k: v for k, v in {'sport': sport, 'market': market, 'date': str(slate_date) if slate_date else ''}.items() if v}
    return '#' + view + ('&' + urlencode(params) if params else '')

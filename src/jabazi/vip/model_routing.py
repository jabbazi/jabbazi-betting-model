"""Audit the actual saved model-to-app routes, without paid collection or promotion."""
from collections import Counter

from .model_diagnostics import REASONS, explanation
from .research import MARKETS, SPORT_CODES, research_link, usable_model

TEAM_MARKETS = ('h2h', 'spreads', 'totals', 'alternate_spreads', 'alternate_totals',
                'team_totals', 'alternate_team_totals')


def _market_report(board, league, market, registry, registry_known):
    rows = [r for r in board['rows'] if r.get('sport') == league and
            str(r.get('market', '')).removesuffix('_alternate') == market]
    props = market.startswith(('player_', 'batter_', 'pitcher_'))
    supported = registry.get('player_supported_markets' if props else 'supported_markets') or []
    model_loaded = market in supported if registry_known else None
    good = [r for r in rows if usable_model(r)]
    reasons = Counter()
    for row in rows:
        if usable_model(row):
            continue
        codes = row.get('probability_unavailable_reasons') or [row.get('probability_unavailable_reason')]
        for code in set(codes):
            reasons[code if code in REASONS else 'MODEL_OR_FEATURES_UNAVAILABLE'] += 1
    stage = ((registry.get('player_market_buckets') or {}).get(market) or {}).get('stage') if props else registry.get('status')
    version = ((registry.get('player_market_buckets') or {}).get(market) or {}).get('model_version') if props else registry.get('version')
    state = ('FORECASTS_AVAILABLE' if good else 'FORECASTS_HELD' if rows else
             'REGISTRY_REFRESHING' if not registry_known else
             'NO_SAVED_QUOTES' if model_loaded else 'MODEL_NOT_LOADED')
    message = {
        'FORECASTS_AVAILABLE': 'Saved forecasts are connected to VIP and Discord research.',
        'FORECASTS_HELD': 'Saved selections exist, but no usable model forecast passes the current checks.',
        'REGISTRY_REFRESHING': 'Model inventory is refreshing; model availability is not yet established.',
        'NO_SAVED_QUOTES': 'The fitted model is loaded; no selection for this market is saved for this slate.',
        'MODEL_NOT_LOADED': 'No fitted model is loaded for this market.',
    }[state]
    return {'market': market, 'kind': 'PLAYER' if props else 'TEAM', 'state': state,
            'message': message, 'model_loaded': model_loaded, 'model_stage': stage or 'UNAVAILABLE',
            'model_version': version, 'saved_rows': len(rows), 'forecast_rows': len(good),
            'projected_total_rows': sum(r.get('projected_mean') is not None for r in good),
            'fresh_price_rows': sum(bool(r.get('price_fresh')) for r in rows),
            'reasons': [{'code': c, 'message': explanation(c), 'rows': n} for c, n in sorted(reasons.items())],
            'app_link': research_link('props' if props else 'moneylines' if market == 'h2h' else 'board',
                                      sport=league, market=market, slate_date=board['date']),
            'approved_for_betting': False}


def routing_report(board, cached_registry, *, sport=''):
    """Artifact inventory is not forecast coverage. Show each independently."""
    if sport and sport not in SPORT_CODES:
        raise ValueError('Unsupported sport')
    data = cached_registry.get('data') or {}
    registry_known = cached_registry.get('data') is not None
    registry = {r.get('sport'): r for r in data.get('models', []) if isinstance(r, dict)}
    leagues = []
    from .data import allowed_market
    from ..models.player_distribution import PLAYER_PROP_MARKETS
    for league, canonical in SPORT_CODES.items():
        if sport and league != sport:
            continue
        reg = registry.get(canonical, {})
        prop_markets = set(MARKETS.get(league, ())) | set(PLAYER_PROP_MARKETS.get(canonical, ())) | set(reg.get('player_supported_markets') or [])
        prop_markets |= {str(r['market']).removesuffix('_alternate') for r in board['rows']
                         if r.get('sport') == league and str(r.get('market', '')).startswith(('player_', 'batter_', 'pitcher_'))}
        props_allowed = allowed_market({'sport': canonical, 'market': 'player_points'})
        markets = list(TEAM_MARKETS) + sorted(prop_markets) if props_allowed else list(TEAM_MARKETS)
        reports = [_market_report(board, league, m, reg, registry_known) for m in markets]
        leagues.append({'sport': league, 'team_model_loaded': bool(reg.get('version')) if registry_known else None,
                        'player_models_loaded': len(reg.get('player_supported_markets') or []) if registry_known else None,
                        'player_policy': 'ALLOWED' if props_allowed else 'POLICY_RESTRICTED',
                        'forecast_rows': sum(r['forecast_rows'] for r in reports), 'markets': reports,
                        'paid_coverage': board.get('paid_coverage', {}).get(league) or None})
    return {'date': board['date'], 'server_time': board.get('server_time'),
            'snapshot_at': board.get('snapshot_at'), 'sources': board.get('sources', []),
            'registry_state': cached_registry.get('state', 'UNAVAILABLE'),
            'registry_has_errors': bool(data.get('errors')), 'sports': leagues,
            'paid_requests_made': 0, 'betting_enabled': False,
            'notice': 'Loaded models, saved selections and usable forecasts are different. '
                      'This reads existing records only; it does not run a scan, create missing probabilities, or approve bets.'}


def compact_report(report):
    """Owner connector audit: counts/reasons only, no licensed player payloads."""
    sports = []
    for league in report['sports']:
        reasons = Counter()
        for market in league['markets']:
            for reason in market['reasons']:
                reasons[reason['code']] += reason['rows']
        sports.append({
            'sport': league['sport'], 'team_model_loaded': league['team_model_loaded'],
            'player_models_loaded': league['player_models_loaded'], 'player_policy': league['player_policy'],
            'team_forecast_rows': sum(m['forecast_rows'] for m in league['markets'] if m['kind'] == 'TEAM'),
            'player_forecast_rows': sum(m['forecast_rows'] for m in league['markets'] if m['kind'] == 'PLAYER'),
            'projected_total_rows': sum(m['projected_total_rows'] for m in league['markets']),
            'markets_with_forecasts': [m['market'] for m in league['markets'] if m['forecast_rows']],
            'markets_with_quotes_but_no_forecast': [m['market'] for m in league['markets'] if m['saved_rows'] and not m['forecast_rows']],
            'unavailable_reason_counts': dict(sorted(reasons.items())),
            'paid_coverage': league['paid_coverage'],
        })
    return {k: report[k] for k in ('date','snapshot_at','sources','paid_requests_made','betting_enabled')} | {'sports': sports}

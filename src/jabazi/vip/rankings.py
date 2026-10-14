"""Today's research rankings with explicit, non-interchangeable evidence labels."""
from datetime import UTC, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .data import age_ok, timestamp, number
from ..discord_daily import sport_label
from .game_research import _usable_model, _valid_probability


def current(row, now):
    start = timestamp(row.get('starts_at'))
    return bool(start and start > now and start.astimezone(ZoneInfo('America/Chicago')).date()
                == now.astimezone(ZoneInfo('America/Chicago')).date()
                and row.get('lifecycle') == 'UPCOMING'
                and row.get('status') not in {'INVALIDATED', 'QUARANTINED', 'SAFETY REVIEW'})


def candidate(row):
    model = _usable_model(row)
    p = _valid_probability(row.get('model_probability')) if model else None
    market = _valid_probability(row.get('market_probability'))
    if p is None and market is None:
        return None
    source = ('VALIDATED MODEL' if row.get('model_stage') == 'PRODUCTION_APPROVED' else 'SHADOW MODEL') if model else 'MARKET-CONSENSUS LEAN'
    return {**row, 'model_probability': p, 'calibrated_probability': None,
            'fair_decimal': 1/p if p else None, 'edge': p-market if p and market else None,
            'ev': p*row['decimal']-1 if p and row.get('decimal') else None,
            'evidence_label': source, 'ranking_probability': p if p else market,
            'probability_basis': 'MODEL' if p else 'MARKET NO-VIG',
            'approved_for_betting': False}


def ranked(rows, *, event_only=False, value=False):
    if value:
        rows = [r for r in rows if r.get('evidence_label') == 'VALIDATED MODEL'
                and r.get('ev') is not None and r['ev'] > 0]
    rows = sorted(rows, key=lambda r: (-(r['ev'] if value else r['ranking_probability']),
                                       -(r.get('decimal') or 0), str(r.get('id'))))
    seen, result = set(), []
    for r in rows:
        key = (r['sport'], r['event_id']) if event_only else (r['sport'], r['event_id'], r.get('player') or r['selection'], r['market'], r.get('line'), r['selection'])
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result[:10]


def research_hub(rows, *, sport='', event_id='', now=None, source_picks=()):
    now = now or datetime.now(UTC)
    today = now.astimezone(ZoneInfo('America/Chicago')).date().isoformat()
    scoped = [r for r in rows if current(r, now) and (not sport or r['sport'] == sport.upper())
              and (not event_id or str(r['event_id']) == event_id)]
    fresh = [r for r in scoped if r.get('fresh') and age_ok(r.get('price_at'), now, 300)]
    candidates = [c for r in fresh if (c := candidate(r)) is not None]
    ml = [r for r in candidates if r['market'] == 'h2h']
    td = [r for r in candidates if r['sport'] == 'NFL' and r['market'] == 'player_anytime_td'
          and str(r['selection']).lower() not in {'no', 'under'}]
    receiving = [r for r in candidates if r['sport'] == 'NFL' and r['market'] == 'player_reception_yds'
                 and str(r['selection']).lower() == 'over' and number(r.get('line')) is not None]
    prop_groups = {}
    for r in candidates:
        if r['sport'] == 'CFB' or not r.get('player') or not str(r['market']).startswith(('player_', 'batter_', 'pitcher_')):
            continue
        if str(r.get('selection', '')).lower() in {'no', 'under'}:
            continue
        prop_groups.setdefault(r['market'], []).append(r)
    events = {(r['sport'], str(r['event_id'])): r for r in scoped}
    evidence = []
    for record in source_picks:
        p = record['payload']
        game = events.get((sport_label(p.get('sport', '')), str(p.get('event_id'))))
        url = urlparse(p.get('source_url') or '')
        if not game or p.get('independently_agreed') is not True or url.scheme != 'https' or not url.hostname or url.username or url.password:
            continue
        if not age_ok(p.get('observed_at'), now, 21600) or not age_ok(p.get('posted_at'), now, 86400):
            continue
        if p.get('market') != 'h2h':
            continue
        # Only consume reviewed discovery evidence, never an author's claimed probability.
        evidence.append({'event_id': game['event_id'], 'event': game['event'], 'sport': game['sport'],
                         'selection': p['selection'], 'evidence_label': 'WEB-RESEARCH LEAN',
                         'source': p['source'], 'source_url': p['source_url'],
                         'published_at': p['posted_at'], 'retrieved_at': p['observed_at'],
                         'model_probability': None, 'approved_for_betting': False})
    # Conflicting reviewed sources do not silently produce a winner.
    selections = {}
    for e in evidence:
        selections.setdefault((e['sport'], e['event_id']), set()).add(e['selection'])
    conflicts = [key[1] for key, values in selections.items() if len(values) > 1]
    evidence = [e for e in evidence if len(selections[(e['sport'], e['event_id'])]) == 1]
    return {'date': today, 'timezone': 'America/Chicago', 'sport': sport.upper(),
            'game_count': len(events), 'fresh_rows': len(fresh), 'stale_rows': len(scoped)-len(fresh),
            'moneyline_likely': ranked(ml, event_only=True), 'moneyline_value': ranked(ml, event_only=True, value=True),
            'anytime_td': ranked(td), 'anytime_td_value': ranked(td, value=True),
            'receiving_overs': ranked(receiving), 'receiving_value': ranked(receiving, value=True),
            'player_markets': {market: ranked(items) for market, items in sorted(prop_groups.items())},
            'receiving_totals': [],
            'receiving_totals_reason': 'The current feed does not expose verified player yardage means. Over-line probabilities are shown separately.',
            'web_leans': evidence[:10], 'conflicting_events': conflicts,
            'web_research_state': 'REVIEWED_EVIDENCE' if evidence else 'UNAVAILABLE',
            'web_research_notice': 'Uses timestamped, independently reviewed source records. Automated web search is not configured; no background browsing is implied.',
            'notice': 'Today only. Up to ten supported entries per list. Probability bases may differ; read each source label. Value requires a production-approved model and a fresh exact price. No list automatically issues a wager.'}

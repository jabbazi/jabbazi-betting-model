"""Private on-demand Discord summaries of the exact same saved VIP board.

No provider calls, wagering authority, public channel posts or model promotion.
Membership and the rules gate are enforced by the existing command handler.
"""
from datetime import UTC, datetime
import re

from .vip.data import board
from .vip.research import moneyline_board, query_board
from .vip.slate_clock import default_slate_date
from .vip.rankings import research_hub, ranked


def safe(value, limit=180):
    text = str('Unavailable' if value is None or value == '' else value).replace('@', '@\u200b')
    return re.sub(r'([\\`*_~|>])', r'\\\1', text)[:limit]


def summary(store, *, view, sport, market='', page=1, now=None, slate_date=None):
    if view not in {'props', 'moneylines', 'top10'} or sport not in {'NBA', 'NFL', 'NHL', 'MLB', 'CFB'}:
        raise ValueError('Unsupported research view or sport')
    if type(page) is not int or not 1 <= page <= 1000 or len(market) > 80:
        raise ValueError('Invalid research page or market')
    now = now or datetime.now(UTC)
    day = slate_date or default_slate_date(now)
    saved = board(store, now=now, slate_date=day)
    fields, selected = [], []
    size = 8
    if view == 'moneylines':
        result = moneyline_board(saved, sport=sport, offset=(page-1)*size, limit=size)
        for game in result['games']:
            model = game['model']
            if model:
                selected.append(model)
                detail = (f"Model winner: {safe(model['selection'])}\n"
                          f"Win probability: {model['model_probability']:.1%} · {safe(model['model_stage'])}\n"
                          f"Model: {safe(model['model_version'], 80)}\nForecast: {safe(model['model_at'], 40)}")
                if not model['fresh']:
                    detail += '\nPrice not verified current; current EV unavailable.'
            else:
                detail = 'Model forecast unavailable. ' + safe(game['reason'])
            fields.append({'name': safe(game['event']), 'value': detail[:700], 'inline': False})
    else:
        if view == 'top10':
            hub = research_hub(saved['rows'], sport=sport, now=now, slate_date=day)
            groups = hub['player_markets']
            rows = groups.get(market, []) if market else ranked(
                [r for group in groups.values() for r in group if r.get('model_probability') is not None], unique_player=True)
            rows = [r for r in rows if r.get('model_probability') is not None]
            start = (page-1)*size
            result = {'rows': rows[start:start+size], 'total': len(rows),
                      'next': start+size if start+size < len(rows) else None}
        else:
            result = query_board(saved, sport=sport, family='props', market=market,
                                 offset=(page-1)*size, limit=size, sort='model')
        for row in result['rows']:
            selected.append(row)
            p = row.get('model_probability')
            detail = (f"{safe(row['event'])}\n{safe(row['selection'])} {safe(row.get('line'))} · {safe(row['market'])}\n"
                      + (f'Model probability: {p:.1%}' if p is not None else 'Model probability unavailable')
                      + f" · {safe(row['model_stage'])}\nModel: {safe(row['model_version'], 80)}")
            if p is None:
                detail += '\n' + safe(row.get('probability_unavailable_message') or 'Current model inputs are unavailable.')
            if row.get('projected_mean') is not None:
                detail += f"\nFitted statistical mean: {row['projected_mean']:.2f} (not hit probability)"
            detail += f"\nForecast: {safe(row['model_at'], 40)} · Price: {safe(row['price_at'], 40)}"
            if not row['fresh']:
                detail += '\nPrice not verified current; current EV unavailable.'
            fields.append({'name': safe(row['player']), 'value': detail[:700], 'inline': False})
    total = result['total']
    description = (f'{day.isoformat()} · America/Chicago · page {page} · {total} matching records.\n'
                   'EXPERIMENTAL RESEARCH — not official picks or betting approval.\n'
                   'Use the private app link for every market, line, side and remaining page.')
    if result['next'] is not None:
        description += f'\nNext page: /{view} sport:{sport} page:{page+1}' + (f' market:{safe(market, 80)}' if market else '')
    if not fields:
        description += '\nNo saved records match this scope. Missing data is not a 0% probability.'
    sources = saved.get('sources', [])
    return {'embed': {'title': f'JABBAZI · {sport} · {view.upper()}',
                      'description': description, 'fields': fields,
                      'footer': {'text': 'Saved snapshots · zero paid requests · no automatic wager'},
                      'color': 0xFF398D},
            'total': total, 'page': page, 'next_page': page+1 if result['next'] is not None else None,
            'row_ids': [r['id'] for r in selected],
            'snapshot_ids': [x['snapshot_id'] for x in sources],
            'slate_date': day.isoformat(), 'paid_requests_made': 0, 'approved_for_betting': False}

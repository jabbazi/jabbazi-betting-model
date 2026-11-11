"""Fetch actual official final boxscores for frozen research forecasts.

Explicit bounded invocation; no scheduler, wagers, quotes, or model promotion.
Missing players/stats remain blocked rather than becoming zero-valued outcomes.
"""
import argparse
from datetime import UTC, datetime
import json
from math import isfinite
import os

import httpx
from sqlalchemy import select

from jabazi.boost_prospective import FORECAST, RESULT, _at, archive_joint_outcome
from jabazi.persistence.store import Store, events, digest
from tools.capture_joint_research import get_json


def count(value):
    number = float(value)
    if not isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError('Verified nonnegative integer statistic required')
    return int(number)


def official_result(http, frozen, forecast_id, *, now=None, source_cache=None):
    def source(url):
        if source_cache is None:
            return get_json(http, url)
        if url not in source_cache:
            source_cache[url] = get_json(http, url)
        return source_cache[url]

    event = frozen['event_id']
    namespace, event_id = event.split(':', 1)
    if not event_id.isdigit():
        raise ValueError('Official event ID required')
    if namespace == 'nhl' and frozen['sport'] == 'icehockey_nhl':
        url = f'https://api-web.nhle.com/v1/gamecenter/{event_id}/boxscore'
        document, checksum = source(url)
        if str(document.get('id')) != event_id:
            raise ValueError('Wrong official event')
        if document.get('gameState') not in {'OFF', 'FINAL'}:
            return {'status': 'PENDING', 'event_id': event}
        start = _at(document['startTimeUTC'], 'official start')
        rows = [p for team in ('awayTeam', 'homeTeam')
                for group in ('forwards', 'defense')
                for p in document['playerByGameStats'][team][group]]
        stats = {'player_goals': 'goals', 'player_assists': 'assists', 'player_shots_on_goal': 'sog'}
        resolved = []
        for leg in frozen['legs']:
            matches = [p for p in rows if str(p.get('playerId')) == leg['player_id']]
            if len(matches) != 1 or leg['market'] not in stats:
                raise ValueError('Exact official player/market result unavailable')
            p = matches[0]
            minutes, seconds = map(int, p['toi'].split(':'))
            if minutes < 0 or not 0 <= seconds < 60 or minutes * 60 + seconds <= 0:
                raise ValueError('Participation unverified; manual DNP review required')
            resolved.append({'leg_id': leg['leg_id'], 'player_id': leg['player_id'],
                'market': leg['market'], 'status': 'final', 'observed_value': count(p[stats[leg['market']]])})
    elif namespace == 'espn-nba' and frozen['sport'] == 'basketball_nba':
        url = f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}'
        document, checksum = source(url)
        header = document['header']
        if str(header.get('id')) != event_id or len(header['competitions']) != 1:
            raise ValueError('Wrong official event')
        game = header['competitions'][0]
        if game['status']['type'].get('completed') is not True or game['status']['type'].get('state') != 'post':
            return {'status': 'PENDING', 'event_id': event}
        start = _at(game['date'], 'official start')
        rows = [(p, group['labels']) for team in document['boxscore']['players']
                for group in team['statistics'] for p in group['athletes']]
        stats = {'player_points': 'PTS', 'player_rebounds': 'REB', 'player_assists': 'AST'}
        resolved = []
        for leg in frozen['legs']:
            matches = [(p, labels) for p, labels in rows if str(p['athlete']['id']) == leg['player_id']]
            if len(matches) != 1 or leg['market'] not in stats:
                raise ValueError('Exact official player/market result unavailable')
            p, labels = matches[0]
            result = {'leg_id': leg['leg_id'], 'player_id': leg['player_id'], 'market': leg['market']}
            if p.get('didNotPlay') is True:
                result['status'] = 'dnp'
            else:
                values = dict(zip(labels, p['stats'], strict=True))
                if len(set(labels)) != len(labels) or float(values['MIN']) <= 0:
                    raise ValueError('Participation unverified')
                result.update(status='final', observed_value=count(values[stats[leg['market']]]))
            resolved.append(result)
    else:
        raise ValueError('Unsupported official forecast namespace')
    observed = now or datetime.now(UTC)
    if start != _at(frozen['starts_at'], 'frozen start') or not start < observed:
        raise ValueError('Official event chronology changed; review required')
    stamp = observed.isoformat()
    return {'status': 'FINAL_OBSERVED', 'leg_results': resolved, 'observed_at': observed,
            'result_source': {'provider': 'official_public_boxscore', 'observed_at': stamp,
                'payload': {'event_id': event, 'ticket_id': frozen['ticket_id'], 'forecast_id': forecast_id,
                    'leg_results': resolved, 'event_status': 'final',
                    'completion_time_basis': 'official_final_status_observed', 'final_observed_at': stamp,
                    'source_url': url, 'raw_response_sha256': checksum, 'raw_response': document}}}


def settle_one(store, http, forecast_id, *, execute=False, source_cache=None):
    with store.engine.connect() as conn:
        existing = conn.execute(select(events.c.id).where(events.c.kind == RESULT,
            events.c.id == digest(['boost_joint_outcome_v1', forecast_id]))).first()
        row = conn.execute(select(events.c.payload).where(events.c.kind == FORECAST,
            events.c.id == forecast_id)).first()
    if existing:
        return {'status': 'ALREADY_RESOLVED', 'forecast_id': forecast_id}
    if row is None:
        raise ValueError('Frozen forecast not found')
    result = official_result(http, row[0], forecast_id, source_cache=source_cache)
    if result['status'] == 'PENDING':
        return result
    if not execute:
        return {'status': 'FINAL_VERIFIED_DRY_RUN', 'forecast_id': forecast_id}
    return archive_joint_outcome(store, forecast_id=forecast_id,
        leg_results=result['leg_results'], result_source=result['result_source'], observed_at=result['observed_at'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forecast', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    store = Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'])
    try:
        with httpx.Client(timeout=15) as http:
            result = settle_one(store, http, args.forecast, execute=args.execute)
    except Exception as exc:
        result = {'status': 'BLOCKED', 'error_type': type(exc).__name__}
    finally:
        store.close()
    print(json.dumps(dict(result, research_only=True, approved_for_betting=False)))


if __name__ == '__main__':
    main()

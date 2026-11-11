"""Explicit bounded research capture using official event/player identities.

No scheduler, paid requests, live-model replacement, Discord action or wagering.
Dry run fetches public inputs; --execute appends genuine private research records.
"""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zlib

import httpx
from sqlalchemy import select

from jabazi.persistence.store import Store, events, digest
from jabazi.research.joint_player_predict import FrozenJointResearchModel
from jabazi.research.player_features import archive_player_feature_snapshot, REQUIRED_INTEGRITY
from jabazi.boost_prospective import _at, _forecast_id, FORECAST

ROOT = Path(__file__).resolve().parents[1]
SPORTS = {'NBA': 'basketball_nba', 'NHL': 'icehockey_nhl'}


def load_frozen_model(sport, root=ROOT):
    base = root/'research_artifacts/joint'
    receipt = json.loads((base/'manifest.json').read_text())['artifacts'][sport]
    compressed = (base/receipt['file']).read_bytes()
    if sha256(compressed).hexdigest() != receipt['compressed_sha256']:
        raise ValueError('Compressed model custody mismatch')
    raw = zlib.decompress(compressed)
    if sha256(raw).hexdigest() != receipt['raw_sha256']:
        raise ValueError('Model custody mismatch')
    artifact = json.loads(raw)
    marginals = {m: json.loads((root/'models/player_props'/sport/(m+'.json')).read_text())
                 for m in artifact['sources']}
    return FrozenJointResearchModel(artifact, marginals,
        expected_sha256=receipt['canonical_sha256'], fitted_at=receipt['fitted_at'])


def get_json(http, url):
    response = http.get(url)
    response.raise_for_status()
    if len(response.content) > 8_000_000:
        raise ValueError('Source response too large')
    return response.json(), sha256(response.content).hexdigest()


def official_scope(http, sport, event, player, now):
    if not str(event).isdigit() or not str(player).isdigit():
        raise ValueError('Official numeric event/player IDs required')
    if sport == 'NHL':
        from jabazi.providers.nhl import NAMES
        document, receipt = get_json(http, f'https://api-web.nhle.com/v1/gamecenter/{event}/landing')
        if str(document.get('id')) != str(event) or document.get('gameState') not in {'FUT', 'PRE'}:
            raise ValueError('Official game is not scheduled pregame')
        start = _at(document['startTimeUTC'], 'official start')
        teams = [document['awayTeam']['abbrev'], document['homeTeam']['abbrev']]
        event_name = ' @ '.join(NAMES[t] for t in teams)
        matches = []
        for team in teams:
            roster, _ = get_json(http, f'https://api-web.nhle.com/v1/roster/{team}/current')
            for category in ('forwards', 'defensemen', 'goalies'):
                for row in roster.get(category, []):
                    if str(row.get('id')) == str(player):
                        matches.append(row['firstName']['default']+' '+row['lastName']['default'])
        namespace = 'nhl'
    else:
        document, receipt = get_json(http, f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event}')
        header = document['header']
        if str(header.get('id')) != str(event) or len(header.get('competitions', [])) != 1:
            raise ValueError('Official NBA event identity unavailable')
        game = header['competitions'][0]
        if game['status']['type'].get('state') != 'pre' or game['status']['type'].get('completed') is True:
            raise ValueError('Official game is not scheduled pregame')
        start = _at(game['date'], 'official start')
        competitors = game['competitors']
        ordered = [[c for c in competitors if c.get('homeAway') == side] for side in ('away', 'home')]
        if any(len(side) != 1 for side in ordered):
            raise ValueError('Ambiguous official NBA teams')
        teams = [side[0]['team'] for side in ordered]
        event_name = ' @ '.join(t['displayName'] for t in teams)
        matches = []
        for team in teams:
            roster, _ = get_json(http, f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team["id"]}/roster')
            for group in roster.get('athletes', []):
                for row in group.get('items', [group]):
                    if str(row.get('id')) == str(player):
                        matches.append(row.get('displayName') or row.get('fullName'))
        namespace = 'espn-nba'
    if len(matches) != 1 or not matches[0] or not now < start:
        raise ValueError('Unique official future player/event scope required')
    return {'sport': SPORTS[sport], 'event_id': namespace+':'+str(event),
            'event': event_name, 'starts_at': start, 'participant': matches[0],
            'player_id': str(player), 'schedule_receipt': receipt}


def collect_inputs(scope, pair, *, now, collector=None):
    if collector is None:
        if scope['sport'] == 'icehockey_nhl':
            from jabazi.providers.nhl_player_features import NHLPlayerFeatureCollector
            collector = NHLPlayerFeatureCollector(now=now, max_seconds=90)
        else:
            from jabazi.providers.nba_player_features import NBAPlayerFeatureCollector
            collector = NBAPlayerFeatureCollector(now=now)
    results = []
    for market in pair:
        card = SimpleNamespace(**scope, market=market, in_play=False)
        payload = collector.snapshot(card)
        if (not payload or str(payload.get('player_id')) != scope['player_id']
                or not all(payload.get('integrity', {}).get(k) is True for k in REQUIRED_INTEGRITY)):
            raise ValueError('Official player features or availability unverified')
        results.append((card, payload))
    return results


def capture(store, model, scope, pair, inputs, *, now):
    # First forecast per event/player/pair/model; reruns do not rewrite evidence.
    identity = digest(['joint_capture_scope_v1', scope['event_id'], scope['player_id'], pair,
                       model.artifact['model_version']])
    previous = store.list_records('joint_capture_receipt', 1, entity=identity)
    if previous:
        return {'status': 'ALREADY_FROZEN', 'forecast_id': previous[0]['payload']['forecast_id']}
    snapshots = []
    for card, payload in inputs:
        ident = archive_player_feature_snapshot(store, sport=scope['sport'],
            event_id=scope['event_id'], participant=scope['participant'], market=card.market,
            player_id=payload['player_id'], starts_at=scope['starts_at'].isoformat(),
            features_available_at=now.isoformat(), features=payload['features'],
            expected_opportunities=payload['expected_opportunities'], integrity=payload['integrity'],
            provider=payload['provider'], source_checksum=payload['source_checksum'],
            feature_schema_version=payload['feature_schema_version'],
            roster_version=payload['roster_version'], injury_version=payload['injury_version'])
        entity = '|'.join((scope['sport'], scope['event_id'], scope['participant'], card.market))
        saved = store.list_records('player_feature_snapshot', 1, entity=entity)[0]['payload']
        if saved['snapshot_id'] != ident:
            raise ValueError('Concurrent feature snapshot changed; retry safely')
        snapshots.append(saved)
    observed = datetime.now(UTC)
    ticket = model.ticket(snapshots, now=observed)
    ticket['model_source']['payload']['schedule_receipt'] = scope['schedule_receipt']
    fid = _forecast_id(ticket['sport'], ticket['event_id'], ticket['ticket_id'], ticket['model_version'])
    with store.engine.connect() as conn:
        existing = conn.execute(select(events.c.id).where(events.c.kind == FORECAST, events.c.id == fid)).first()
    if existing:
        return {'status': 'ALREADY_FROZEN', 'forecast_id': fid}
    from jabazi.boost_prospective import freeze_joint_ticket
    result = freeze_joint_ticket(store, ticket, observed_at=observed)
    store.append('joint_capture_receipt', identity, {'forecast_id': result['forecast_id'],
                 'research_only': True}, digest(['joint_capture_receipt', identity]))
    return {'status': 'FROZEN', 'forecast_id': result['forecast_id'], 'snapshots': len(snapshots)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=SPORTS, required=True)
    parser.add_argument('--event', required=True)
    parser.add_argument('--player', required=True)
    parser.add_argument('--pair', type=int, choices=(0, 1, 2), default=0)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    store = None
    try:
        model = load_frozen_model(SPORTS[args.sport])
        pair = tuple(model.artifact['buckets'][args.pair]['markets'])
        now = datetime.now(UTC)
        with httpx.Client(timeout=15, follow_redirects=False) as http:
            scope = official_scope(http, args.sport, args.event, args.player, now)
        inputs = collect_inputs(scope, pair, now=now)
        result = {'status': 'INPUTS_VERIFIED_DRY_RUN', 'snapshots': len(inputs)}
        if args.execute:
            store = Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'])
            result = capture(store, model, scope, pair, inputs, now=now)
        result.update(research_only=True, approved_for_betting=False,
                      sportsbook_quote_captured=False, results_captured=False)
    except Exception as exc:
        # No credential-bearing upstream exceptions or raw licensed inputs.
        result = {'status': 'BLOCKED', 'error_type': type(exc).__name__,
                  'research_only': True, 'approved_for_betting': False}
    finally:
        if store is not None:
            store.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] != 'BLOCKED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
